"""
Configuração do gunicorn em produção (lida pelo Dockerfile).

Threads em vez de muitos processos: as callbacks passam a maior parte do
tempo esperando o PostgreSQL ou as APIs (o "Atualizar" consulta Meta e Google
por alguns segundos), e thread esperando I/O não segura a CPU.
"""

import os

# Sempre na 7000 — a porta combinada para o painel. Plataformas como o
# Easypanel injetam `PORT` (80) e apontam o proxy para ela; ouvindo só na
# `PORT`, um domínio configurado para a 7000 dava "Service is not reachable"
# com o app de pé. Ouvindo nas duas, qualquer uma das configurações funciona.
APP_PORT = os.getenv("APP_PORT", "7000")
bind = [f"0.0.0.0:{port}" for port in dict.fromkeys([APP_PORT, os.getenv("PORT") or APP_PORT])]
worker_class = "gthread"
workers = int(os.getenv("WEB_WORKERS", "2"))
threads = int(os.getenv("WEB_THREADS", "8"))

# O "Atualizar" busca as duas APIs antes de responder; 30 s (o padrão)
# derrubaria a requisição no meio em conta grande.
timeout = int(os.getenv("WEB_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Carrega o app uma vez antes de criar os processos: o `init_db()` (criação de
# schema e migrações) roda uma vez só, não uma por processo disputando o banco.
preload_app = True

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("WEB_LOG_LEVEL", "info")
