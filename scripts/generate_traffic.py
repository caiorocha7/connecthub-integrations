"""Send realistic signed webhooks to the seeded demo endpoint (populates the dashboard).

Usage: python scripts/generate_traffic.py [--count 40]
Uses the demo credentials (DEMO_USER_EMAIL / DEMO_USER_PASSWORD) to reveal the endpoint secret,
then sends orders while toggling the simulator between normal, 500 and 429 modes.
All traffic goes through the real API -> PostgreSQL -> Redis -> worker -> simulator pipeline.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import random
import time

import httpx

API = os.environ.get("CONNECTHUB_API", "http://localhost:8130").rstrip("/")
SIM = os.environ.get("CONNECTHUB_SIMULATOR", "http://localhost:8131").rstrip("/")
EMAIL = os.environ.get("DEMO_USER_EMAIL", "demo@example.com")
PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "Demo@12345")
NAMES = ["Maria Silva", "João Souza", "Ana Lima", "Pedro Costa", "Carla Rocha", "Lucas Alves"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--fail", action="store_true", help="keep the simulator failing (500) for every event")
    args = parser.parse_args()
    c = httpx.Client(timeout=10)
    tokens = c.post(f"{API}/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    tokens.raise_for_status()
    h = {"Authorization": f"Bearer {tokens.json()['access_token']}"}
    org = c.get(f"{API}/api/v1/auth/me", headers=h).json()["memberships"][0]["organization_id"]
    base = f"{API}/api/v1/orgs/{org}"
    endpoint = c.get(f"{base}/endpoints", headers=h).json()[0]
    secret = c.get(f"{base}/endpoints/{endpoint['id']}/secret", headers=h).json()["signing_secret"]
    url = f"{API}/api/v1/ingest/{endpoint['public_id']}"

    c.post(f"{SIM}/control/reset")
    if args.fail:
        c.put(f"{SIM}/control", json={"mode": "error", "status_code": 500})
    sent = dup = 0
    for i in range(args.count):
        if not args.fail and i == int(args.count * 0.4):
            c.put(f"{SIM}/control", json={"mode": "error", "status_code": 503, "fail_next": 6})
        if not args.fail and i == int(args.count * 0.7):
            c.put(f"{SIM}/control", json={"mode": "rate_limit", "retry_after": 3, "fail_next": 3})
        order_id = f"ord_{int(time.time())}_{i:03d}"
        payload = {
            "id": order_id,
            "type": "order.paid",
            "data": {
                "customer": {"name": random.choice(NAMES), "email": f"CLIENTE{i}@EXAMPLE.COM", "cpf": "000.000.000-00"},
                "total": f"{random.uniform(40, 900):.2f}",
                "currency": "BRL",
                "items": [{"sku": f"CH-{random.randint(1, 40):03d}", "qty": str(random.randint(1, 4))}],
                "paid_at": "2026-11-03T12:00:00Z",
            },
        }
        body = json.dumps(payload).encode()
        repeats = 2 if i % 9 == 0 else 1  # some retransmissions to show idempotency
        for _ in range(repeats):
            ts = str(int(time.time()))
            sig = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
            r = c.post(
                url,
                content=body,
                headers={"Content-Type": "application/json", "X-ConnectHub-Timestamp": ts, "X-ConnectHub-Signature": f"v1={sig}"},
            )
            if r.status_code == 200:
                dup += 1
            elif r.status_code == 202:
                sent += 1
        time.sleep(0.15)
    print(f"sent {sent} events ({dup} duplicates blocked) to {endpoint['name']}")


if __name__ == "__main__":
    main()
