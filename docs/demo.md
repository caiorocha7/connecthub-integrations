# Demonstração: falhas, retentativas, reprocessamento e idempotência

Este roteiro mostra o principal diferencial do ConnectHub: nenhum evento se perde quando o destino falha, e
retransmissões não geram entregas duplicadas. Ele pode ser executado de forma **automatizada** (script) ou
**manual** (pela interface).

## Preparação

```bash
cp .env.example .env
docker compose up -d --build --wait
```

Para acelerar a demonstração, o `.env.example` usa `RETRY_BASE_SECONDS=2`. Com isso as retentativas acontecem em
segundos (≈1–2 s, 2–4 s, 4–8 s…), com o teto definido por `RETRY_MAX_SECONDS`.

## Opção A: script automatizado

```bash
pip install -r tests/e2e/requirements.txt     # só httpx
python tests/e2e/demo_scenario.py
```

O script usa a API, o PostgreSQL, o Redis, o worker e o simulador reais e termina com código ≠ 0 se qualquer
verificação falhar. Saída obtida em uma execução real:

```
[1] Criar conta/organização, endpoint e destino
    ✔ endpoint ep_4d45… → destino http://simulator:8131/hooks/demo-1309f9 (máx. 3 tentativas)
[2] Configurar o simulador para responder HTTP 500
[3] Enviar webhook válido e assinado (HMAC-SHA256)
    ✔ HTTP 202 Accepted — event_id=2849…, entregas lógicas=1
    ✔ webhook com assinatura inválida rejeitado com 401 (não persistido)
[4] Observar o evento persistido e enviado à fila
    ✔ evento persistido no PostgreSQL com status RECEIVED; payload mascarado: {'total': '259.90', 'customer': {'cpf': '***'}}
    ✔ outbox publicado no Redis e consumido pelo worker Celery
[5] Acompanhar as tentativas com falha (backoff exponencial + jitter)
    • tentativa #1 [AUTO] HTTP 500 RETRYABLE_ERROR erro=http_5xx próxima=17:09:21
    • tentativa #2 [AUTO] HTTP 500 RETRYABLE_ERROR erro=http_5xx próxima=17:09:25
    • tentativa #3 [AUTO] HTTP 500 RETRYABLE_ERROR erro=http_5xx
    ✔ entrega FAILED após 3 tentativas; último erro: destino respondeu HTTP 500
[6] Restaurar o simulador
[7] Reprocessamento manual autorizado e auditado
[8] Confirmar sucesso e histórico completo
    • tentativa #4 [MANUAL] HTTP 200 SUCCESS
    ✔ entrega SUCCEEDED; evento SUCCEEDED; 4 tentativas registradas
    ✔ auditoria: 1 registro(s) de delivery.replay por demo-1309f9@example.com
[9] Reenviar o mesmo identificador de evento
    ✔ HTTP 200 duplicate=true — mesmo event_id 2849…
[10] Comprovar que a duplicidade não gerou nova entrega lógica
    ✔ entregas lógicas do evento: 1; duplicados bloqueados: 1
    ✔ simulador recebeu 4 requisições para o evento (3 falhas + 1 sucesso) — nenhuma após o duplicado
[+] Falha transitória curada por retry automático (fail_next=2)
    • tentativa #1 [AUTO] HTTP 503 … • tentativa #2 [AUTO] HTTP 503 … • tentativa #3 [AUTO] HTTP 200 SUCCESS
Cenário concluído com sucesso.
```

Ao final, o script imprime o e-mail do usuário criado (senha `Demo12345`). Com ele é possível entrar na UI e ver
o mesmo cenário no dashboard.

## Opção B: roteiro manual pela interface

1. Acesse http://localhost:4230 e entre com `demo@example.com` / `Demo@12345`.
2. **Endpoints**: abra "Loja Virtual — pedidos", criado pelo seed. Clique em **Revelar** para copiar o segredo e a
   URL de ingestão. O card "Como enviar" traz o comando `curl` com a assinatura.
3. **Destinos**: o "ERP (simulador)" aponta para `http://simulator:8131/hooks/erp`, com 4 tentativas e timeout de
   5 s.
4. **Simulador**: clique em **Erro 5xx**.
5. Envie um webhook assinado. Pelo terminal (Git Bash, Linux ou macOS):

   ```bash
   SECRET='<segredo revelado>'; URL='<url de ingestão>'
   BODY='{"id":"ord_demo_1","type":"order.paid","data":{"total":"99.90","customer":{"name":"Maria","email":"MARIA@EXAMPLE.COM"}}}'
   TS=$(date +%s); SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')
   curl -i -X POST "$URL" -H 'Content-Type: application/json' -H "X-ConnectHub-Timestamp: $TS" -H "X-ConnectHub-Signature: v1=$SIG" -d "$BODY"
   ```

   A resposta esperada é `HTTP/1.1 202 Accepted`.
6. **Eventos**: o evento aparece como `Recebido` e depois `Retentando`. Abra o detalhe para ver o payload
   (campos sensíveis mascarados) e a entrega.
7. **Entregas → detalhe**: a linha do tempo mostra cada tentativa com HTTP 500, duração e horário da próxima
   tentativa. O dashboard (atualizado a cada 10 s) mostra as falhas e o "Em retry".
8. **Simulador**: clique em **Operação normal**.
   - Se a entrega ainda estiver em `RETRYING`, a próxima tentativa automática terá sucesso.
   - Se já estiver `FAILED`, vá em **Falhas & reprocesso** e clique em **Reprocessar**.
9. Confirme `Sucesso` na entrega: a tentativa final aparece como `reprocesso manual` ou `automática`. Em
   **Configurações → Auditoria** fica o registro `delivery.replay`.
10. Repita o mesmo `curl` (mesmo `id`, novo timestamp). A resposta é `HTTP 200` com `"duplicate": true`. Em
    **Eventos**, a coluna "Duplicados" mostra `1× bloqueado`, e em **Simulador** nenhuma nova requisição chega para
    `ord_demo_1`.

### Outras falhas para explorar

| Modo do simulador | Comportamento esperado |
| --- | --- |
| **Timeout** (atraso de 30 s > timeout de 5 s do destino) | `error_type=timeout`, retentativa com backoff |
| **Rate limit (429)** com `Retry-After: 5` | O próximo agendamento respeita no mínimo 5 s |
| **Erro 5xx** com "falhar apenas as próximas N = 2" | Duas falhas seguidas de sucesso automático |
| Destino com URL para `http://169.254.169.254/` | Cadastro recusado (SSRF) com `422` |

### Recuperação de infraestrutura (opcional)

```bash
docker compose stop redis           # broker fora do ar
# envie webhooks: a API continua respondendo 202 (evento + outbox persistidos)
docker compose start redis          # o relay publica as mensagens pendentes em segundos
docker compose kill worker          # mata o worker no meio do processamento
docker compose start worker         # acks_late + recovery retomam as entregas
```

O card "Outbox pendente" no dashboard mostra o backlog acumulado enquanto o Redis está fora.

## Gerar volume para o dashboard

```bash
python scripts/generate_traffic.py --count 40   # alterna normal, 503 e 429 e inclui retransmissões
python scripts/generate_traffic.py --count 4 --fail   # cria falhas definitivas para a tela de reprocesso
```
