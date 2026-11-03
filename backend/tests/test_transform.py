from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.transform import RuleValidationError, TransformError, transform_payload

PAYLOAD = {
    "id": "ord_1",
    "data": {
        "customer": {"email": "  ANA@EXAMPLE.COM ", "name": "Ana"},
        "total": "149.90",
        "paid": "true",
        "items": [{"sku": "A1", "qty": "2"}, {"sku": "B2", "qty": "1"}],
        "created": 1700000000,
    },
}


def test_rename_select_default_and_convert() -> None:
    mappings = [
        {"target": "order_id", "source": "id"},
        {"target": "customer.email", "source": "$.data.customer.email", "transform": "trim"},
        {"target": "customer.email_lower", "source": "data.customer.email", "transform": "lower"},
        {"target": "amount", "source": "data.total", "type": "float"},
        {"target": "paid", "source": "data.paid", "type": "boolean"},
        {"target": "first_sku", "source": "data.items[0].sku"},
        {"target": "first_qty", "source": "data.items[0].qty", "type": "integer"},
        {"target": "currency", "source": "data.currency", "default": "BRL"},
        {"target": "created_at", "source": "data.created", "type": "datetime"},
        {"target": "origin", "value": "connecthub"},
        {"target": "lines[1].sku", "source": "data.items[1].sku"},
    ]
    out = transform_payload(mappings, False, PAYLOAD)
    assert out == {
        "order_id": "ord_1",
        "customer": {"email": "ANA@EXAMPLE.COM", "email_lower": "  ana@example.com "},
        "amount": 149.9,
        "paid": True,
        "first_sku": "A1",
        "first_qty": 2,
        "currency": "BRL",
        "created_at": "2023-11-14T22:13:20+00:00",
        "origin": "connecthub",
        "lines": [None, {"sku": "B2"}],
    }


def test_include_unmapped_and_original_preserved() -> None:
    out = transform_payload([{"target": "extra", "value": 1}], True, PAYLOAD)
    assert out["id"] == "ord_1" and out["extra"] == 1
    assert "extra" not in PAYLOAD


def test_missing_optional_is_skipped_and_required_fails() -> None:
    assert transform_payload([{"target": "x", "source": "nope"}], False, PAYLOAD) == {}
    with pytest.raises(TransformError):
        transform_payload([{"target": "x", "source": "nope", "required": True}], False, PAYLOAD)


def test_invalid_conversion_raises() -> None:
    with pytest.raises(TransformError):
        transform_payload(
            [{"target": "n", "source": "data.customer.name", "type": "integer"}], False, PAYLOAD
        )


@pytest.mark.parametrize(
    "mapping",
    [
        {"target": "a", "source": "data.__import__('os')"},
        {"target": "a; drop", "source": "id"},
        {"target": "", "source": "id"},
        {"target": "a"},
        {"target": "a", "source": "id", "type": "eval"},
        {"target": "a", "source": "id", "transform": "exec"},
    ],
)
def test_rule_validation_rejects_unsafe_or_invalid(mapping: dict[str, str]) -> None:
    with pytest.raises(RuleValidationError):
        transform_payload([mapping], False, PAYLOAD)


def test_preview_and_crud_endpoints(client: TestClient, admin) -> None:  # type: ignore[no-untyped-def]
    base = f"/api/v1/orgs/{admin.org_id}/transform-rules"
    preview = client.post(
        f"{base}/preview",
        json={
            "mappings": [{"target": "total", "source": "data.total", "type": "float"}],
            "sample_payload": PAYLOAD,
        },
        headers=admin.headers,
    )
    assert preview.status_code == 200
    assert preview.json() == {"valid": True, "output": {"total": 149.9}, "errors": []}

    bad = client.post(
        f"{base}/preview",
        json={"mappings": [{"target": "x", "source": "a b"}], "sample_payload": {}},
        headers=admin.headers,
    )
    assert bad.json()["valid"] is False and bad.json()["errors"]

    created = client.post(
        base,
        json={
            "name": "Pedido -> ERP",
            "mappings": [{"target": "order_id", "source": "id"}],
            "sample_payload": PAYLOAD,
        },
        headers=admin.headers,
    )
    assert created.status_code == 201
    rule_id = created.json()["id"]
    invalid = client.patch(
        f"{base}/{rule_id}", json={"mappings": [{"target": "x", "source": "bad path"}]}, headers=admin.headers
    )
    assert invalid.status_code == 422
    assert client.get(f"{base}/{rule_id}", headers=admin.headers).json()["mappings"] == [
        {"target": "order_id", "source": "id", "type": "keep", "required": False}
    ]
    assert client.delete(f"{base}/{rule_id}", headers=admin.headers).status_code == 204
