# Worker (Celery)

O worker executa as entregas HTTP de forma independente da API. Ele usa o mesmo pacote de domínio
(`backend/app`), mas roda em um processo e container separados, e escala horizontalmente:

```bash
docker compose up -d --scale worker=3
```

- Imagem: `worker/Dockerfile`, construída com o contexto `./backend` (veja `docker-compose.yml`).
- Filas: `deliveries` (entregas) e `maintenance` (relay do outbox e recuperação).
- Agendador: o serviço `beat` (mesma imagem) dispara `connecthub.relay_outbox` a cada
  `OUTBOX_RELAY_INTERVAL_SECONDS` e `connecthub.recover` a cada 30 s.
- Garantias: `acks_late` + `task_reject_on_worker_lost` (at-least-once). O claim no PostgreSQL torna cada execução
  segura contra duplicidade.

Código: `backend/app/worker/` (tasks finas) e `backend/app/services/delivery.py`, `outbox.py`, `recovery.py`.

Execução local sem Docker (a partir de `backend/`):

```bash
celery -A app.worker.celery_app worker -Q deliveries,maintenance -P solo --loglevel=INFO
celery -A app.worker.celery_app beat --loglevel=INFO
```
