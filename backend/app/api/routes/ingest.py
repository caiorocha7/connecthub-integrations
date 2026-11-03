"""Public webhook ingestion route (no human login; authenticated by the endpoint's HMAC secret)."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.logging import log_context
from app.schemas.events import IngestResponse
from app.services.ingest import IngestError, ingest_webhook

router = APIRouter(tags=["ingest"])


class PayloadTooLarge(Exception):
    pass


async def _read_limited_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise PayloadTooLarge
        except ValueError:
            raise PayloadTooLarge from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise PayloadTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


@router.post(
    "/ingest/{public_id}",
    response_model=IngestResponse,
    status_code=202,
    responses={
        200: {"description": "Evento duplicado (já recebido); nenhuma nova entrega criada"},
        202: {"description": "Evento aceito e persistido"},
        400: {"description": "JSON inválido"},
        401: {"description": "Assinatura ausente, inválida ou expirada"},
        404: {"description": "Endpoint inexistente ou inativo"},
        413: {"description": "Payload acima do limite"},
        415: {"description": "Content-Type deve ser application/json"},
    },
)
async def ingest(
    public_id: str, request: Request, background: BackgroundTasks, db: DbSession
) -> JSONResponse:
    settings = get_settings()
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        return JSONResponse({"detail": "Content-Type deve ser application/json"}, status_code=415)
    try:
        raw_body = await _read_limited_body(request, settings.max_payload_bytes)
    except PayloadTooLarge:
        return JSONResponse(
            {"detail": f"payload excede o limite de {settings.max_payload_bytes} bytes"}, status_code=413
        )

    headers = {k.lower(): v for k, v in request.headers.items()}
    with log_context(endpoint=public_id):
        try:
            result = await run_in_threadpool(
                ingest_webhook,
                db,
                public_id=public_id,
                raw_body=raw_body,
                headers=headers,
                source_ip=request.client.host if request.client else None,
            )
        except IngestError as exc:
            db.rollback()
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    if result.outbox_ids:
        from app.worker.tasks import dispatch_now

        background.add_task(dispatch_now, result.outbox_ids)

    body = IngestResponse(
        event_id=result.event_id,
        external_event_id=result.external_event_id,
        status=result.status,
        duplicate=result.duplicate,
        deliveries=result.deliveries,
    )
    return JSONResponse(body.model_dump(mode="json"), status_code=200 if result.duplicate else 202)
