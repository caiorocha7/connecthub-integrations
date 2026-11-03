"""Idempotent development seed: demo user, organization, simulator destination and endpoint.

Run with ``python -m app.seed``. Credentials come from DEMO_USER_EMAIL / DEMO_USER_PASSWORD and are
for local demonstration only. The seed refuses to run when ENVIRONMENT=production.
"""

from __future__ import annotations

import sys

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import encrypt_secret, generate_public_id, generate_signing_secret, hash_password
from app.db.session import SessionLocal
from app.models import Destination, Endpoint, Membership, Organization, Role, Route, TransformRule, User

SAMPLE_ORDER = {
    "id": "ord_1001",
    "type": "order.paid",
    "data": {
        "customer": {"name": "Maria Silva", "email": "MARIA@EXAMPLE.COM", "document": "000.000.000-00"},
        "total": "259.90",
        "currency": "BRL",
        "items": [{"sku": "CH-001", "qty": "2"}],
        "paid_at": "2026-01-15T14:32:00Z",
    },
}


def run() -> int:
    settings = get_settings()
    if settings.environment == "production":
        print("seed disabled in production")
        return 1
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == settings.demo_user_email))
        if user is not None:
            print(f"seed: demo user already exists ({settings.demo_user_email})")
            return 0
        user = User(
            email=settings.demo_user_email,
            full_name="Demo Admin",
            password_hash=hash_password(settings.demo_user_password),
        )
        org = Organization(name="ConnectHub Demo", slug="connecthub-demo")
        db.add_all([user, org])
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role=Role.ADMIN))
        rule = TransformRule(
            organization_id=org.id,
            name="Pedido pago → ERP",
            description="Normaliza o pedido do e-commerce para o formato do ERP",
            include_unmapped=False,
            mappings=[
                {"target": "external_id", "source": "id", "type": "string", "required": True},
                {"target": "customer.name", "source": "data.customer.name", "type": "string"},
                {
                    "target": "customer.email",
                    "source": "data.customer.email",
                    "type": "string",
                    "transform": "lower",
                },
                {"target": "amount", "source": "data.total", "type": "float", "required": True},
                {"target": "currency", "source": "data.currency", "default": "BRL", "type": "string"},
                {"target": "paid_at", "source": "data.paid_at", "type": "datetime"},
                {"target": "source", "value": "connecthub"},
            ],
            sample_payload=SAMPLE_ORDER,
        )
        destination = Destination(
            organization_id=org.id,
            name="ERP (simulador)",
            description="Destino simulado para demonstrar falhas e recuperação",
            url="http://simulator:8131/hooks/erp",
            headers={"X-Api-Version": "2026-01"},
            timeout_seconds=5,
            max_attempts=4,
        )
        endpoint = Endpoint(
            organization_id=org.id,
            name="Loja Virtual — pedidos",
            description="Webhooks de pedidos pagos do e-commerce",
            public_id=generate_public_id(),
            secret_encrypted=encrypt_secret(generate_signing_secret()),
            event_id_path="id",
        )
        db.add_all([rule, destination, endpoint])
        db.flush()
        db.add(
            Route(
                organization_id=org.id,
                endpoint_id=endpoint.id,
                destination_id=destination.id,
                transform_rule_id=rule.id,
            )
        )
        db.commit()
        print(f"seed: created demo user {settings.demo_user_email} and organization 'ConnectHub Demo'")
    return 0


if __name__ == "__main__":
    sys.exit(run())
