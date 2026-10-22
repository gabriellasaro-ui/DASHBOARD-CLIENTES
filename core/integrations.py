"""Clientes REST oficiais da Meta Marketing API e Google Ads API.

Os segredos são globais da agência e vêm do ambiente. O banco guarda somente
o identificador da conta que pertence a cada tenant.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class IntegrationError(RuntimeError):
    def __init__(self, platform: str, message: str, *, request_id: str | None = None):
        super().__init__(message)
        self.platform = platform
        self.request_id = request_id


def _digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


class MetaAdsClient:
    def __init__(self):
        self.access_token = os.getenv("META_ADS_ACCESS_TOKEN", "").strip()
        self.version = os.getenv("META_ADS_API_VERSION", "v25.0").strip() or "v25.0"
        if not self.version.startswith("v"):
            self.version = f"v{self.version}"
        self.base_url = f"https://graph.facebook.com/{self.version}"
        self._cooldown_until = 0.0
        self._cooldown_lock = threading.Lock()
        self._creative_cache: dict[str, dict[str, dict]] = {}
        self._creative_cached_at: dict[str, float] = {}
        self._creative_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            raise IntegrationError("meta", "Token da Meta Ads não configurado.")
        with self._cooldown_lock:
            if time.time() < self._cooldown_until:
                raise IntegrationError(
                    "meta",
                    "A Meta limitou temporariamente as consultas. A proxima tentativa sera automatica.",
                )
        response = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params={**(params or {}), "access_token": self.access_token},
            timeout=45,
        )
        if not response.ok:
            try:
                error = response.json().get("error", {})
            except ValueError:
                error = {}
            raw_message = error.get("message") or "A Meta Ads recusou a consulta."
            rate_limited = "request limit" in raw_message.lower() or error.get("code") in (4, 17, 32)
            if rate_limited:
                with self._cooldown_lock:
                    self._cooldown_until = time.time() + 10 * 60
                message = "A Meta atingiu o limite temporario de consultas. Nova tentativa automatica em ate 10 minutos."
            else:
                message = raw_message
            raise IntegrationError(
                "meta",
                message,
                request_id=error.get("fbtrace_id") or response.headers.get("x-fb-trace-id"),
            )
        return response.json()

    def _all(self, path: str, params: dict | None = None, max_pages: int = 20) -> list[dict]:
        payload = self._get(path, params)
        rows = list(payload.get("data", []))
        page = 1
        while payload.get("paging", {}).get("next") and page < max_pages:
            response = requests.get(payload["paging"]["next"], timeout=45)
            if not response.ok:
                # Parar no meio e devolver o que veio gravaria um período
                # incompleto como se fosse o total. Melhor falhar e manter os
                # dados anteriores no banco.
                raise IntegrationError("meta", "A Meta interrompeu a paginação da consulta.")
            payload = response.json()
            rows.extend(payload.get("data", []))
            page += 1
        return rows

    def list_ad_accounts(self) -> list[dict]:
        rows = self._all(
            "me/adaccounts",
            {"fields": "id,name,account_status,currency", "limit": 500},
        )
        return [
            {
                "id": row.get("id"),
                "name": row.get("name") or row.get("id"),
                "status": row.get("account_status"),
                "currency": row.get("currency"),
            }
            for row in rows
        ]

    def insights(
        self,
        account_id: str,
        *,
        start: str,
        end: str,
        level: str,
        time_increment: int | None = None,
    ) -> list[dict]:
        """
        Entrega e ações chegam em DUAS consultas, juntadas por dia e entidade.

        Pedir `actions` na mesma chamada que `spend` com `time_increment=1`
        faz a Meta devolver gasto e impressões ZERADOS em algumas contas —
        sem erro nenhum. Na Somaxi, 30 dias que somavam R$ 6.564,95 vinham
        como R$ 0,00 no nível de conta e R$ 149,67 somando os anúncios. Cada
        grupo de campos sozinho volta íntegro. (`cost_per_action_type` saiu:
        não era usado e, na quebra diária, esvaziava a resposta inteira.)
        """
        entity_fields = {
            "account": [],
            "campaign": ["campaign_id", "campaign_name"],
            "adset": ["campaign_id", "campaign_name", "adset_id", "adset_name"],
            "ad": ["campaign_id", "campaign_name", "adset_id", "adset_name", "ad_id", "ad_name"],
        }
        id_field = {"account": None, "campaign": "campaign_id", "adset": "adset_id", "ad": "ad_id"}[level]
        base = {
            "level": level,
            "time_range": json.dumps({"since": start, "until": end}),
            "limit": 500,
        }
        if time_increment:
            base["time_increment"] = time_increment

        delivery = self._all(
            f"{account_id}/insights",
            {**base, "fields": ",".join(entity_fields[level] + list(self.DELIVERY_FIELDS))},
            max_pages=self.INSIGHT_PAGES,
        )
        actions = self._all(
            f"{account_id}/insights",
            {**base, "fields": ",".join(([id_field] if id_field else []) + list(self.ACTION_FIELDS))},
            max_pages=self.INSIGHT_PAGES,
        )

        def key(row: dict) -> tuple:
            return row.get("date_start"), str(row.get(id_field) or "") if id_field else ""

        by_key = {key(row): row for row in delivery}
        for row in actions:
            target = by_key.get(key(row))
            if target is None:
                # Ação atribuída a um dia sem entrega (conversão atrasada):
                # entra com entrega zerada para o lead não sumir.
                target = by_key.setdefault(key(row), {
                    "date_start": row.get("date_start"),
                    "date_stop": row.get("date_stop"),
                    **({id_field: row.get(id_field)} if id_field else {}),
                })
            for field in self.ACTION_FIELDS:
                if row.get(field):
                    target[field] = row[field]
        return list(by_key.values())

    def window_totals(self, account_id: str, start: str, end: str) -> dict:
        """
        Totais da conta no período inteiro, numa consulta SEM quebra por dia.

        Serve a duas coisas:

        * **Alcance.** A Meta não devolve mais `reach` na quebra diária (vem
          vazio), e alcance não se soma entre dias — a mesma pessoa contaria
          uma vez por dia. O alcance de um período só existe pedido assim.
        * **Conferência da coleta diária**, ver `core.sync.fetch_meta_rows`.
        """
        rows = self._all(
            f"{account_id}/insights",
            {
                "level": "account",
                "fields": "spend,impressions,reach",
                "time_range": json.dumps({"since": start, "until": end}),
            },
        )
        row = rows[0] if rows else {}

        def number(key):
            try:
                return float(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        return {"spend": number("spend"), "impressions": number("impressions"), "reach": number("reach")}

    # `reach` e `frequency` ficam de fora: na quebra diária a Meta os devolve
    # vazios. O alcance vem de `window_totals`.
    DELIVERY_FIELDS = ("spend", "impressions", "clicks", "ctr", "cpc", "cpm")
    ACTION_FIELDS = ("actions", "action_values")
    # 20 páginas de 500 cortavam em silêncio a quebra diária por anúncio de
    # contas grandes (60 dias x centenas de anúncios). O total ficava menor
    # que o do Gerenciador sem nenhum aviso.
    INSIGHT_PAGES = 400

    def entity_statuses(self, account_id: str, entity: str) -> dict[str, str]:
        edge = {"campaign": "campaigns", "adset": "adsets", "ad": "ads"}[entity]
        return {
            str(row.get("id")): row.get("effective_status") or row.get("status") or "ACTIVE"
            for row in self._all(
                f"{account_id}/{edge}",
                {"fields": "id,effective_status,status", "limit": 500},
            )
            if row.get("id")
        }

    @staticmethod
    def _creative_image_url(creative: dict) -> tuple[str | None, str | None]:
        """Prioriza a imagem original e usa thumbnail somente como fallback."""
        story = creative.get("object_story_spec") or {}
        video = story.get("video_data") or {}
        link = story.get("link_data") or {}
        photo = story.get("photo_data") or {}
        assets = creative.get("asset_feed_spec") or {}

        original_candidates = [
            creative.get("image_url"),
            video.get("image_url"),
            photo.get("image_url"),
            link.get("image_url"),
            link.get("picture"),
            *[
                item.get("url")
                for item in assets.get("images", [])
                if isinstance(item, dict)
            ],
            *[
                item.get("picture") or item.get("image_url")
                for item in link.get("child_attachments", [])
                if isinstance(item, dict)
            ],
        ]
        for url in original_candidates:
            if url:
                return url, "original"
        if creative.get("thumbnail_url"):
            return creative["thumbnail_url"], "thumbnail"
        return None, None

    CREATIVE_FIELDS = (
        "id,status,effective_status,creative{id,image_url,thumbnail_url,"
        "object_story_spec,asset_feed_spec}"
    )
    CREATIVE_BATCH = 40

    def _creative_rows_by_ids(self, ad_ids: list[str]) -> list[dict]:
        """
        Busca os criativos em lotes, pelo endpoint de múltiplos objetos.

        Pedir `{conta}/ads` inteiro fazia a Meta recusar com "Please reduce the
        amount of data you're asking for" em conta com muitos anúncios — a
        expansão de `creative` é pesada e o limite é do TAMANHO da resposta,
        não da contagem de itens. Em lote, cada resposta é pequena; e se ainda
        assim a Meta reclamar, o lote é dividido pela metade e reenviado.
        """
        rows: list[dict] = []
        pending = [ad_ids[index:index + self.CREATIVE_BATCH]
                   for index in range(0, len(ad_ids), self.CREATIVE_BATCH)]

        while pending:
            chunk = pending.pop()
            try:
                payload = self._get(
                    "",
                    {
                        "ids": ",".join(chunk),
                        "fields": self.CREATIVE_FIELDS,
                        # Se não houver original, pede a maior miniatura aceita.
                        "thumbnail_width": 1080,
                        "thumbnail_height": 1080,
                    },
                )
            except IntegrationError as exc:
                if len(chunk) > 1 and "reduce the amount of data" in str(exc).lower():
                    middle = len(chunk) // 2
                    pending.extend([chunk[:middle], chunk[middle:]])
                    continue
                raise
            # A resposta vem como {id: objeto}, não como lista em "data".
            rows.extend(value for value in payload.values() if isinstance(value, dict))

        return rows

    def ad_creatives(self, account_id: str, ad_ids: set[str] | None = None) -> dict[str, dict]:
        """Relaciona cada anúncio à melhor imagem disponível no criativo."""
        with self._creative_lock:
            cached = self._creative_cache.get(account_id, {})
            fresh = time.time() - self._creative_cached_at.get(account_id, 0) < 60 * 60
            if fresh and (ad_ids is None or ad_ids.issubset(cached.keys())):
                return {key: value for key, value in cached.items() if ad_ids is None or key in ad_ids}

        if ad_ids:
            rows = self._creative_rows_by_ids(sorted(ad_ids))
        else:
            # Sem lista de anúncios não há como lotear: pagina com um limite
            # pequeno o bastante para a resposta caber.
            rows = self._all(
                f"{account_id}/ads",
                {
                    "fields": self.CREATIVE_FIELDS,
                    "limit": 50,
                    "thumbnail_width": 1080,
                    "thumbnail_height": 1080,
                },
                max_pages=40,
            )
        result = {}
        fallbacks = []
        for row in rows:
            ad_id = str(row.get("id") or "")
            if not ad_id or (ad_ids is not None and ad_id not in ad_ids):
                continue
            creative = row.get("creative") or {}
            url, quality = self._creative_image_url(creative)
            result[ad_id] = {
                "url": url,
                "quality": quality,
                "status": row.get("effective_status") or row.get("status") or "ACTIVE",
            }
            if quality == "thumbnail" and creative.get("id"):
                fallbacks.append((ad_id, str(creative["id"])))

        # `thumbnail_url` dentro da expansão de `ads` costuma ser 64x64.
        # Consultar o criativo diretamente faz a Meta honrar 1080x1080.
        def large_thumbnail(ad_id: str, creative_id: str):
            try:
                payload = self._get(
                    creative_id,
                    {
                        "fields": "thumbnail_url",
                        "thumbnail_width": 1080,
                        "thumbnail_height": 1080,
                    },
                )
                return ad_id, payload.get("thumbnail_url")
            except IntegrationError:
                return ad_id, None

        if fallbacks:
            with ThreadPoolExecutor(max_workers=min(8, len(fallbacks))) as pool:
                futures = [pool.submit(large_thumbnail, ad_id, creative_id) for ad_id, creative_id in fallbacks]
                for future in as_completed(futures):
                    ad_id, url = future.result()
                    if url:
                        result[ad_id] = {
                            **result.get(ad_id, {}),
                            "url": url,
                            "quality": "large_thumbnail",
                        }
        with self._creative_lock:
            self._creative_cache[account_id] = result
            self._creative_cached_at[account_id] = time.time()
        return result


class GoogleAdsClient:
    def __init__(self):
        self.developer_token = os.getenv("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
        self.client_id = os.getenv("GOOGLE_ADS_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "").strip()
        self.refresh_token = os.getenv("GOOGLE_ADS_REFRESH_TOKEN", "").strip()
        self.login_customer_id = _digits(os.getenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
        self.version = os.getenv("GOOGLE_ADS_API_VERSION", "v25").strip() or "v25"
        if not self.version.startswith("v"):
            self.version = f"v{self.version}"
        self.base_url = f"https://googleads.googleapis.com/{self.version}"
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._token_lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return all(
            [self.developer_token, self.client_id, self.client_secret, self.refresh_token, self.login_customer_id]
        )

    def _token(self) -> str:
        if not self.configured:
            raise IntegrationError("google", "Credenciais do Google Ads não configuradas.")
        with self._token_lock:
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token
            response = requests.post(
                "https://www.googleapis.com/oauth2/v3/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                },
                timeout=30,
            )
            if not response.ok:
                try:
                    detail = response.json().get("error_description")
                except ValueError:
                    detail = None
                raise IntegrationError("google", detail or "Não foi possível renovar o acesso ao Google Ads.")
            payload = response.json()
            self._access_token = payload["access_token"]
            self._expires_at = time.time() + int(payload.get("expires_in", 3600))
            return self._access_token

    def search(self, customer_id: str, query: str) -> list[dict]:
        customer_id = _digits(customer_id)
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "developer-token": self.developer_token,
            "login-customer-id": self.login_customer_id,
            "Content-Type": "application/json",
        }
        response = requests.post(
            f"{self.base_url}/customers/{customer_id}/googleAds:searchStream",
            headers=headers,
            json={"query": " ".join(query.split())},
            timeout=60,
        )
        if not response.ok:
            request_id = response.headers.get("request-id") or response.headers.get("google-ads-request-id")
            try:
                body = response.json()
                message = body.get("error", {}).get("message")
            except ValueError:
                message = None
            raise IntegrationError(
                "google",
                message or "O Google Ads recusou a consulta.",
                request_id=request_id,
            )
        rows: list[dict] = []
        for batch in response.json():
            rows.extend(batch.get("results", []))
        return rows

    def list_customer_accounts(self) -> list[dict]:
        query = """
            SELECT customer_client.client_customer, customer_client.descriptive_name,
                   customer_client.level, customer_client.manager, customer_client.status
            FROM customer_client
            WHERE customer_client.level <= 1
        """
        rows = self.search(self.login_customer_id, query)
        accounts = []
        for row in rows:
            item = row.get("customerClient", {})
            customer_id = item.get("clientCustomer", "").split("/")[-1]
            if not customer_id or item.get("manager") or customer_id == self.login_customer_id:
                continue
            accounts.append(
                {
                    "id": customer_id,
                    "name": item.get("descriptiveName") or customer_id,
                    "status": item.get("status"),
                }
            )
        return accounts


meta_ads = MetaAdsClient()
google_ads = GoogleAdsClient()
