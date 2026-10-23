"""Sessão e autorização compartilhadas pelas páginas Dash e pelo Flask."""

from __future__ import annotations

from flask import g, has_request_context, session

from core.storage import get_tenant, get_user, set_last_tenant

# Sessão e tenant não mudam no meio de uma requisição, mas eram consultados
# no banco a cada chamada — e são chamados de dezenas de lugares ao montar
# uma tela. Uma resolução por requisição, guardada em `flask.g`.
_USER_KEY = "_pulse_user"
_TENANT_KEY = "_pulse_tenant"


def invalidate_request_cache() -> None:
    """Chamado quando a própria sessão muda no meio da requisição."""
    if not has_request_context():
        return
    for key in (_USER_KEY, _TENANT_KEY, "_pulse_brand_colors"):
        if hasattr(g, key):
            delattr(g, key)


def current_user() -> dict | None:
    if not has_request_context():
        return None

    if hasattr(g, _USER_KEY):
        return getattr(g, _USER_KEY)

    user = _load_user()
    setattr(g, _USER_KEY, user)
    return user


def _load_user() -> dict | None:
    """
    O usuário da sessão, no cliente que está aberto (`active_tenant_id`).

    Quem não é master precisa de pelo menos um cliente ativo: se todos os
    acessos dele foram removidos ou suspensos, a sessão acaba aqui.
    """
    user = get_user(session.get("user_id"), session.get("active_tenant_id"))
    if not user or not user.get("active"):
        session.clear()
        return None
    if user["role"] != "superadmin":
        if not user.get("tenant_id"):
            session.clear()
            return None
        # O cliente pedido pode ter sido removido desde o último clique;
        # `get_user` caiu em outro, e a sessão passa a apontar para ele.
        session["active_tenant_id"] = user["tenant_id"]
    return user


def sign_in(user: dict, remember: bool = False) -> None:
    session.clear()
    session["user_id"] = user["id"]
    if user.get("role") != "superadmin" and user.get("tenant_id"):
        session["active_tenant_id"] = user["tenant_id"]
    session.permanent = bool(remember)
    invalidate_request_cache()


def sign_out() -> None:
    session.clear()
    invalidate_request_cache()


def is_superadmin(user: dict | None = None) -> bool:
    user = user or current_user()
    return bool(user and user.get("role") == "superadmin")


def active_tenant(user: dict | None = None) -> dict | None:
    """Tenant efetivo: o próprio para cliente; o selecionado para o master."""
    if user is None and has_request_context() and hasattr(g, _TENANT_KEY):
        return getattr(g, _TENANT_KEY)

    resolved = _load_tenant(user or current_user())
    if user is None and has_request_context():
        setattr(g, _TENANT_KEY, resolved)
    return resolved


def _load_tenant(user: dict | None) -> dict | None:
    if not user:
        return None
    if not is_superadmin(user):
        # O cliente aberto já foi resolvido em `get_user` (só clientes a que
        # a pessoa tem acesso entram ali).
        return get_tenant(user.get("tenant_id"))

    # O master só vê um cliente quando ESCOLHE um. Antes, sem escolha, caía
    # no primeiro cliente ativo — e todo login abria direto na Reconlog, sem
    # que ninguém tivesse pedido.
    tenant_id = session.get("active_tenant_id") if has_request_context() else None
    tenant = get_tenant(tenant_id)
    if tenant and tenant.get("status") == "active":
        return tenant
    return None


def select_active_tenant(tenant_id: int) -> dict:
    """
    Abre outro cliente. O master abre qualquer um; os demais, só os clientes
    em que têm acesso — o id vem do navegador e não pode ser confiado.
    """
    user = current_user()
    if not user:
        raise PermissionError("Sessão expirada.")
    if not is_superadmin(user) and not any(
        item["tenant_id"] == tenant_id for item in user.get("memberships") or []
    ):
        raise PermissionError("Você não tem acesso a este cliente.")
    tenant = get_tenant(tenant_id)
    if not tenant or tenant.get("status") != "active":
        raise ValueError("Cliente não encontrado ou inativo.")
    session["active_tenant_id"] = tenant["id"]
    if not is_superadmin(user):
        # Na próxima entrada a pessoa volta para o cliente em que estava.
        set_last_tenant(user["id"], tenant["id"])
    invalidate_request_cache()
    return tenant


def can_edit_appearance(user: dict | None, tenant: dict | None) -> bool:
    """
    Quem pode mudar a aparência do painel de um cliente.

    O responsável da empresa (convidado como "Responsável") e o master. O
    visualizador não: a aparência vale para todos os acessos da empresa, e
    quem só acompanha os números não deveria redesenhar a tela dos outros.
    """
    if not user or not tenant:
        return False
    if is_superadmin(user):
        return True
    return user.get("role") == "client_admin" and user.get("tenant_id") == tenant.get("id")


# --------------------------------------------------------------------------
# Simulação de acesso
# --------------------------------------------------------------------------
#
# O master já enxerga os dados de qualquer cliente pelo seletor de contas.
# A simulação existe para ver a interface EXATAMENTE como o responsável vê —
# sem o menu de administração, com a marca e as permissões dele. O id do
# administrador fica guardado à parte para o caminho de volta existir sempre;
# sem isso, quem simula fica preso na conta do cliente.

IMPERSONATOR_KEY = "impersonator_id"


def start_impersonation(user_id: int, tenant_id: int | None = None) -> dict:
    """
    Vê o painel como a pessoa vê. `tenant_id` é o cliente de onde o master
    clicou: a mesma pessoa pode estar em vários, com papéis diferentes.
    """
    admin = current_user()
    if not is_superadmin(admin):
        raise PermissionError("Somente o administrador pode simular um acesso.")

    target = get_user(user_id, tenant_id)
    if not target or not target.get("active"):
        raise ValueError("Acesso não encontrado ou inativo.")
    if target.get("role") == "superadmin":
        raise ValueError("Não há o que simular em outra conta de administrador.")
    if not target.get("tenant_id"):
        raise ValueError("Esta pessoa não tem nenhum cliente ativo.")

    session["user_id"] = target["id"]
    session[IMPERSONATOR_KEY] = admin["id"]
    session["active_tenant_id"] = target["tenant_id"]
    invalidate_request_cache()
    return target


def stop_impersonation() -> dict | None:
    admin_id = session.get(IMPERSONATOR_KEY)
    if not admin_id:
        return None
    session.pop(IMPERSONATOR_KEY, None)
    session["user_id"] = admin_id
    session.pop("active_tenant_id", None)
    invalidate_request_cache()
    return get_user(admin_id)


def impersonator() -> dict | None:
    """Administrador por trás da simulação, quando houver uma em curso."""
    if not has_request_context():
        return None
    return get_user(session.get(IMPERSONATOR_KEY))


def initials(name: str | None) -> str:
    words = [word for word in (name or "").split() if word]
    return "".join(word[0] for word in words[:2]).upper() or "US"
