# API do ConnectHub

A documentação interativa completa (OpenAPI 3, gerada pelo FastAPI) fica em:

- Swagger UI: http://localhost:8130/docs
- ReDoc: http://localhost:8130/redoc
- Esquema: http://localhost:8130/openapi.json

Este documento resume os contratos principais.

## Convenções

- Base: `/api/v1`. Rotas privadas exigem `Authorization: Bearer <access_token>`.
- Recursos de tenant: `/api/v1/orgs/{org_id}/…`. Recurso de outra organização responde `404`.
- Erros: `{"detail": "mensagem"}`. Erros de validação respondem `422` com
  `{"detail": "dados inválidos", "errors": [{"field": "...", "message": "..."}]}`.
- Paginação: `?page=1&page_size=20`, com resposta `{items, total, page, page_size, pages}`.
- Datas em ISO 8601 com fuso horário.

## Autenticação

| Método | Rota | Corpo | Resposta |
| --- | --- | --- | --- |
| POST | `/auth/register` | `{email, password, full_name, organization_name?}` | `201` tokens (o usuário vira ADMIN da nova organização) |
| POST | `/auth/login` | `{email, password}` | `200` `{access_token, refresh_token, token_type, expires_in}` |
| POST | `/auth/refresh` | `{refresh_token}` | `200` novo par; o token antigo é revogado (rotação) |
| POST | `/auth/logout` | `{refresh_token}` | `204` (revoga o refresh token) |
| GET | `/auth/me` | - | usuário + vínculos (`memberships[]` com `role`) |
| PATCH | `/auth/me` | `{full_name}` | perfil atualizado |
| POST | `/auth/change-password` | `{current_password, new_password}` | `204` (revoga todas as sessões) |

Reusar um refresh token já rotacionado revoga **todos** os refresh tokens do usuário (detecção de roubo).

## Organizações e membros

| Método | Rota | Papel |
| --- | --- | --- |
| GET / POST | `/orgs` | autenticado (quem cria vira ADMIN) |
| GET / PATCH | `/orgs/{org}` | membro / ADMIN |
| GET | `/orgs/{org}/members` | membro |
| POST | `/orgs/{org}/members` `{email, role}` | ADMIN (o usuário precisa existir) |
| PATCH / DELETE | `/orgs/{org}/members/{membership_id}` | ADMIN (a organização mantém ao menos 1 ADMIN) |
| GET | `/orgs/{org}/audit-logs?action=` | ADMIN |

## Endpoints, destinos e regras

| Método | Rota | Observações |
| --- | --- | --- |
| GET / POST | `/orgs/{org}/endpoints` | POST (ADMIN) devolve `signing_secret` **uma única vez** |
| GET / PATCH / DELETE | `/orgs/{org}/endpoints/{id}` | DELETE responde `409` se houver histórico (desative em vez de excluir) |
| POST | `/orgs/{org}/endpoints/{id}/rotate-secret` `{grace_period_minutes}` | o segredo anterior continua válido durante a carência |
| GET | `/orgs/{org}/endpoints/{id}/secret` | ADMIN, auditado |
| POST | `/orgs/{org}/endpoints/{id}/routes` `{destination_id, transform_rule_id?}` | associa um destino |
| PATCH / DELETE | `/orgs/{org}/endpoints/{id}/routes/{route_id}` | `{transform_rule_id?, clear_transform?, is_active?}` |
| GET / POST | `/orgs/{org}/destinations` | URL validada contra SSRF (`422` se bloqueada) |
| GET / PATCH / DELETE | `/orgs/{org}/destinations/{id}` | `headers` não pode conter Host, Content-Type, X-ConnectHub-* etc. |
| GET / POST | `/orgs/{org}/transform-rules` | regra validada (`422` com a lista de erros) |
| GET / PATCH / DELETE | `/orgs/{org}/transform-rules/{id}` | |
| POST | `/orgs/{org}/transform-rules/preview` `{mappings, include_unmapped, sample_payload}` | `{valid, output, errors}` |

### Formato de um mapeamento

```json
{ "target": "customer.email", "source": "data.customer.email", "type": "string",
  "transform": "lower", "default": null, "required": true }
{ "target": "origin", "value": "connecthub" }
```

- `source`: caminho com pontos e índices (`data.items[0].sku`); `$.` no início é aceito.
- `type`: `keep`, `string`, `integer`, `float`, `boolean` ou `datetime` (gera ISO 8601 em UTC).
- `transform`: `trim`, `lower` ou `upper`.
- `include_unmapped: true` copia o payload original e sobrescreve os campos mapeados.

## Ingestão pública

```
POST /api/v1/ingest/{public_id}
Content-Type: application/json
X-ConnectHub-Timestamp: 1767225600
X-ConnectHub-Signature: v1=<hex(HMAC_SHA256(secret, timestamp + "." + corpo_bruto))>
X-ConnectHub-Event-Id: ord_1001        (opcional)
```

| Status | Significado |
| --- | --- |
| `202` | Evento novo persistido; `{event_id, external_event_id, status, duplicate:false, deliveries}` |
| `200` | Duplicado; `duplicate:true` e o mesmo `event_id`, sem nova entrega |
| `400` | Corpo não é JSON objeto ou lista |
| `401` | Assinatura ausente, inválida ou timestamp fora da janela (padrão 300 s) |
| `404` | Endpoint inexistente ou inativo |
| `413` | Payload acima de `MAX_PAYLOAD_BYTES` (padrão 256 KB) |
| `415` | `Content-Type` diferente de `application/json` |

O identificador do evento é resolvido nesta ordem: header `X-ConnectHub-Event-Id`, depois o caminho
`event_id_path` do endpoint no payload (padrão `id`), depois `sha256:` do corpo bruto.

### Assinando em Python

```python
import hashlib, hmac, json, time, httpx

body = json.dumps({"id": "ord_1001", "total": "259.90"}).encode()
ts = str(int(time.time()))
sig = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
httpx.post(INGEST_URL, content=body, headers={
    "Content-Type": "application/json",
    "X-ConnectHub-Timestamp": ts,
    "X-ConnectHub-Signature": f"v1={sig}",
})
```

Assine **exatamente os bytes enviados**. Reserializar o JSON depois de assinar invalida a assinatura.

### Assinando com curl

```bash
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')
curl -X POST "$INGEST_URL" -H 'Content-Type: application/json' \
  -H "X-ConnectHub-Timestamp: $TS" -H "X-ConnectHub-Signature: v1=$SIG" -d "$BODY"
```

## Requisição enviada ao destino

```
POST <url do destino>
Content-Type: application/json
User-Agent: ConnectHub-Webhooks/1.0
X-ConnectHub-Event-Id: ord_1001
X-ConnectHub-Delivery-Id: <uuid>
X-ConnectHub-Attempt: 2
Idempotency-Key: <uuid da entrega, estável entre tentativas>
X-ConnectHub-Timestamp / X-ConnectHub-Signature   (se o destino tiver segredo de assinatura)
<headers configurados no destino>
```

## Histórico, replay e dashboard

| Método | Rota | Filtros / observações |
| --- | --- | --- |
| GET | `/orgs/{org}/events` | `status, endpoint_id, destination_id, date_from, date_to, search, page, page_size` |
| GET | `/orgs/{org}/events/{id}` | payload e headers mascarados + entregas |
| POST | `/orgs/{org}/events/{id}/replay` | reprocessa as entregas `FAILED` do evento (`409` se não houver) |
| GET | `/orgs/{org}/deliveries` | `status, endpoint_id, destination_id, event_id, date_from, date_to` |
| GET | `/orgs/{org}/deliveries/{id}` | tentativas, payload transformado (mascarado) |
| POST | `/orgs/{org}/deliveries/{id}/replay` | só `FAILED` (`409` caso contrário); auditado |
| GET | `/orgs/{org}/dashboard/summary?hours=24` | KPIs, `timeline[]`, `destinations[]`, `recent_failures[]`, `outbox_pending` |

## Saúde

- `GET /health` responde `{"status":"ok"}` (liveness).
- `GET /health/ready` verifica PostgreSQL e Redis; responde `503` se algum estiver indisponível.

## Simulador (porta 8131)

| Método | Rota | Descrição |
| --- | --- | --- |
| POST / PUT / PATCH | `/hooks/{nome}` | recebe a entrega e responde conforme o modo |
| GET / PUT | `/control` | `{mode: normal\|error\|timeout\|rate_limit, status_code, delay_seconds, retry_after, fail_next}` |
| POST | `/control/reset` | volta ao modo normal e limpa o histórico |
| GET / DELETE | `/requests?event_id=&limit=` | requisições recebidas, `succeeded`, `unique_successful_deliveries` |
