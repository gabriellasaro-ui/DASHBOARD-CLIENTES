"""
Configuração do gunicorn em produção (lida pelo Dockerfile).

Threads em vez de muitos processos: as callbacks passam a maior parte do
tempo esperando o PostgreSQL ou as APIs (o "Atualizar" consulta Meta e Google
por alguns segundos), e thread esperando I/O não segura a CPU.
"""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '7000')}"
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
