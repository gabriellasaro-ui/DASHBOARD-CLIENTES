# Painel de performance — imagem única para o site (gunicorn) e o
# sincronizador (sync_worker.py). O docker-compose.yml escolhe o comando.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # "Últimos 30 dias" termina ONTEM no horário de Brasília. Em UTC, depois
    # das 21h o painel já consideraria o dia seguinte.
    TZ=America/Sao_Paulo \
    PORT=7000

# tzdata: sem ele a variável TZ acima é ignorada e o container fica em UTC.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependências antes do código: mudar uma linha de Python não reinstala tudo.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Sem root. `runtime/` guarda a trava do sincronizador.
RUN useradd --create-home --uid 1000 painel \
    && mkdir -p runtime data \
    && chown -R painel:painel /app/runtime /app/data
USER painel

EXPOSE 7000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"7000\")}/login', timeout=4)"

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:server"]
