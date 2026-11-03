"""ConnectHub — end-to-end resilience demo against the REAL running stack.

Exercises API + PostgreSQL + outbox + Redis + Celery worker + failure simulator:

 1. Create an organization (new account), an endpoint and a destination
 2. Put the simulator in "HTTP 500" mode
 3. Send a valid, HMAC-signed webhook
 4. Observe the event persisted and enqueued
 5. Follow the failing attempts (backoff) until the attempts are exhausted
 6. Restore the simulator
 7. Trigger a manual (audited) replay
 8. Confirm success and the full attempt history
 9. Re-send the same event id
10. Prove the duplicate did NOT create a new logical delivery
Bonus: transient failure (fail_next=2) healed by automatic retries, no human action.

Usage (stack running via `docker compose up -d`):
    python tests/e2e/demo_scenario.py
Env: CONNECTHUB_API (default http://localhost:8130), CONNECTHUB_SIMULATOR (default http://localhost:8131),
     DEMO_DESTINATION_URL (default http://simulator:8131/hooks/<name>, reachable from the worker container).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx

API = os.environ.get("CONNECTHUB_API", "http://localhost:8130").rstrip("/")
SIM = os.environ.get("CONNECTHUB_SIMULATOR", "http://localhost:8131").rstrip("/")
DEST_BASE = os.environ.get("DEMO_DESTINATION_URL", "http://simulator:8131/hooks")

GREEN, RED, YELLOW, CYAN, BOLD, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    GREEN = RED = YELLOW = CYAN = BOLD = RESET = ""

client = httpx.Client(timeout=15)


def step(n: int | str, text: str) -> None:
    print(f"\n{BOLD}{CYAN}[{n}]{RESET} {BOLD}{text}{RESET}")


def ok(text: str) -> None:
    print(f"    {GREEN}✔{RESET} {text}")


def info(text: str) -> None:
    print(f"    {YELLOW}•{RESET} {text}")


def fail(text: str) -> None:
    print(f"\n{RED}✘ {text}{RESET}")
    sys.exit(1)


def check(resp: httpx.Response, *expected: int) -> Any:
    if resp.status_code not in expected:
        fail(f"{resp.request.method} {resp.request.url} -> {resp.status_code}: {resp.text[:400]}")
    return resp.json() if resp.content else None


def wait_for(description: str, probe: Callable[[], Any], timeout: float = 60, interval: float = 1.0) -> Any:
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(interval)
    fail(f"timeout aguardando: {description}")


def sign(secret: str, body: bytes) -> dict[str, str]:
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-ConnectHub-Timestamp": ts, "X-ConnectHub-Signature": f"v1={digest}"}


def send_webhook(ingest_url: str, secret: str, payload: dict[str, Any]) -> httpx.Response:
    body = json.dumps(payload).encode()
    return client.post(ingest_url, content=body, headers=sign(secret, body))


def show_attempts(org_url: str, headers: dict[str, str], delivery_id: str) -> dict[str, Any]:
    detail: dict[str, Any] = check(client.get(f"{org_url}/deliveries/{delivery_id}", headers=headers), 200)
    for a in detail["attempts"]:
        code = a["status_code"] if a["status_code"] is not None else "—"
        extra = f" erro={a['error_type']}" if a["error_type"] else ""
        retry = f" próxima={a['next_retry_at'][11:19]}" if a["next_retry_at"] else ""
        info(f"tentativa #{a['attempt_number']} [{a['trigger']}] HTTP {code} {a['outcome']}{extra}{retry}")
    return detail


def main() -> None:
    print(f"{BOLD}ConnectHub — cenário de resiliência ponta a ponta{RESET}")
    print(f"API={API}  SIMULADOR={SIM}")
    check(client.get(f"{API}/health/ready"), 200)
    check(client.get(f"{SIM}/health"), 200)
    run = uuid.uuid4().hex[:6]

    # 1 ---------------------------------------------------------------------------------------
    step(1, "Criar conta/organização, endpoint e destino")
    email = f"demo-{run}@example.com"
    tokens = check(
        client.post(
            f"{API}/api/v1/auth/register",
            json={
                "email": email,
                "password": "Demo12345",
                "full_name": "Demo Runner",
                "organization_name": f"Demo {run}",
            },
        ),
        201,
    )
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    me = check(client.get(f"{API}/api/v1/auth/me", headers=headers), 200)
    org_id = me["memberships"][0]["organization_id"]
    org_url = f"{API}/api/v1/orgs/{org_id}"
    ok(f"usuário {email} (ADMIN) na organização {org_id}")

    endpoint = check(
        client.post(f"{org_url}/endpoints", json={"name": f"Pedidos {run}", "event_id_path": "id"}, headers=headers),
        201,
    )
    hook = f"demo-{run}"
    destination = check(
        client.post(
            f"{org_url}/destinations",
            json={
                "name": f"ERP simulado {run}",
                "url": f"{DEST_BASE}/{hook}",
                "timeout_seconds": 3,
                "max_attempts": 3,
            },
            headers=headers,
        ),
        201,
    )
    check(
        client.post(
            f"{org_url}/endpoints/{endpoint['id']}/routes",
            json={"destination_id": destination["id"]},
            headers=headers,
        ),
        201,
    )
    ingest_url, secret = endpoint["ingest_url"], endpoint["signing_secret"]
    if not ingest_url.startswith(API):
        ingest_url = f"{API}/api/v1/ingest/{endpoint['public_id']}"
    ok(f"endpoint {endpoint['public_id']} → destino {destination['url']} (máx. 3 tentativas)")

    # 2 ---------------------------------------------------------------------------------------
    step(2, "Configurar o simulador para responder HTTP 500")
    check(client.post(f"{SIM}/control/reset"), 200)
    check(client.put(f"{SIM}/control", json={"mode": "error", "status_code": 500}), 200)
    ok("simulador em modo erro 500")

    # 3 ---------------------------------------------------------------------------------------
    step(3, "Enviar webhook válido e assinado (HMAC-SHA256)")
    event_ext_id = f"ord_{run}"
    payload = {"id": event_ext_id, "type": "order.paid", "data": {"total": "259.90", "customer": {"cpf": "000"}}}
    r = check(send_webhook(ingest_url, secret, payload), 202)
    event_id = r["event_id"]
    ok(f"HTTP 202 Accepted — event_id={event_id}, entregas lógicas={r['deliveries']}")
    bad = send_webhook(ingest_url, "whsec_wrong", {"id": "forged"})
    if bad.status_code != 401:
        fail(f"assinatura inválida deveria ser 401, veio {bad.status_code}")
    ok("webhook com assinatura inválida rejeitado com 401 (não persistido)")

    # 4 ---------------------------------------------------------------------------------------
    step(4, "Observar o evento persistido e enviado à fila")
    event = check(client.get(f"{org_url}/events/{event_id}", headers=headers), 200)
    ok(f"evento persistido no PostgreSQL com status {event['status']}; payload mascarado: {event['payload']['data']}")
    delivery_id = event["deliveries"][0]["id"]

    def first_attempt() -> bool:
        d = check(client.get(f"{org_url}/deliveries/{delivery_id}", headers=headers), 200)
        return len(d["attempts"]) >= 1

    wait_for("primeira tentativa do worker", first_attempt, timeout=30, interval=0.5)
    ok("outbox publicado no Redis e consumido pelo worker Celery")

    # 5 ---------------------------------------------------------------------------------------
    step(5, "Acompanhar as tentativas com falha (backoff exponencial + jitter)")

    def exhausted() -> dict[str, Any] | None:
        d: dict[str, Any] = check(client.get(f"{org_url}/deliveries/{delivery_id}", headers=headers), 200)
        return d if d["status"] == "FAILED" else None

    wait_for("esgotamento das tentativas", exhausted, timeout=90)
    detail = show_attempts(org_url, headers, delivery_id)
    ok(f"entrega FAILED após {detail['attempt_count']} tentativas; último erro: {detail['last_error']}")
    summary = check(client.get(f"{org_url}/dashboard/summary", headers=headers), 200)
    ok(f"dashboard: recebidos={summary['events_received']} falhas={summary['deliveries_failed']}")

    # 6 ---------------------------------------------------------------------------------------
    step(6, "Restaurar o simulador")
    check(client.put(f"{SIM}/control", json={"mode": "normal"}), 200)
    ok("simulador em operação normal")

    # 7 ---------------------------------------------------------------------------------------
    step(7, "Reprocessamento manual autorizado e auditado")
    replay = check(client.post(f"{org_url}/deliveries/{delivery_id}/replay", headers=headers), 200)
    ok(f"replay aceito: {replay['replayed']} entrega(s)")

    # 8 ---------------------------------------------------------------------------------------
    step(8, "Confirmar sucesso e histórico completo")

    def succeeded() -> dict[str, Any] | None:
        d: dict[str, Any] = check(client.get(f"{org_url}/deliveries/{delivery_id}", headers=headers), 200)
        return d if d["status"] == "SUCCEEDED" else None

    wait_for("sucesso após replay", succeeded, timeout=30, interval=0.5)
    detail = show_attempts(org_url, headers, delivery_id)
    event = check(client.get(f"{org_url}/events/{event_id}", headers=headers), 200)
    ok(f"entrega SUCCEEDED; evento {event['status']}; {len(detail['attempts'])} tentativas registradas")
    audit = check(client.get(f"{org_url}/audit-logs", params={"action": "delivery.replay"}, headers=headers), 200)
    ok(f"auditoria: {audit['total']} registro(s) de delivery.replay por {audit['items'][0]['actor_email']}")

    # 9 ---------------------------------------------------------------------------------------
    step(9, "Reenviar o mesmo identificador de evento")
    dup = check(send_webhook(ingest_url, secret, {**payload, "note": "retransmissão"}), 200)
    if not dup["duplicate"] or dup["event_id"] != event_id:
        fail(f"esperado duplicado do evento {event_id}, recebido {dup}")
    ok(f"HTTP 200 duplicate=true — mesmo event_id {dup['event_id']}")

    # 10 --------------------------------------------------------------------------------------
    step(10, "Comprovar que a duplicidade não gerou nova entrega lógica")
    time.sleep(4)  # give the worker a chance to (wrongly) deliver again
    deliveries = check(client.get(f"{org_url}/deliveries", params={"event_id": event_id}, headers=headers), 200)
    sim = check(client.get(f"{SIM}/requests", params={"event_id": event_ext_id, "limit": 100}), 200)
    event = check(client.get(f"{org_url}/events/{event_id}", headers=headers), 200)
    if deliveries["total"] != 1:
        fail(f"esperada 1 entrega lógica, encontradas {deliveries['total']}")
    if sim["succeeded"] != 1:
        fail(f"esperada 1 resposta 2xx no destino, encontradas {sim['succeeded']}")
    ok(f"entregas lógicas do evento: {deliveries['total']}; duplicados bloqueados: {event['duplicate_count']}")
    ok(
        f"simulador recebeu {sim['matched']} requisições para o evento "
        f"({sim['matched'] - sim['succeeded']} falhas + {sim['succeeded']} sucesso) — nenhuma após o duplicado"
    )

    # Bonus -----------------------------------------------------------------------------------
    step("+", "Falha transitória curada por retry automático (fail_next=2)")
    check(client.put(f"{SIM}/control", json={"mode": "error", "status_code": 503, "fail_next": 2}), 200)
    r = check(send_webhook(ingest_url, secret, {"id": f"ord_{run}_b", "type": "order.paid"}), 202)
    auto_event = check(client.get(f"{org_url}/events/{r['event_id']}", headers=headers), 200)
    auto_delivery = auto_event["deliveries"][0]["id"]

    def auto_ok() -> bool:
        d = check(client.get(f"{org_url}/deliveries/{auto_delivery}", headers=headers), 200)
        if d["status"] == "FAILED":
            fail("entrega transitória falhou definitivamente")
        return bool(d["status"] == "SUCCEEDED")

    wait_for("sucesso via retry automático", auto_ok, timeout=60, interval=0.5)
    show_attempts(org_url, headers, auto_delivery)
    ok("2 falhas 503 seguidas de sucesso automático, sem intervenção humana")

    check(client.post(f"{SIM}/control/reset"), 200)
    print(f"\n{GREEN}{BOLD}Cenário concluído com sucesso.{RESET} Login na UI: {email} / Demo12345")


if __name__ == "__main__":
    main()
