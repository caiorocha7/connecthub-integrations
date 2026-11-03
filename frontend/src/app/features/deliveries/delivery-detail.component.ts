import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { DeliveryDetail } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

const TRIGGER_LABEL: Record<string, string> = {
  AUTO: 'automática',
  MANUAL: 'reprocesso manual',
  RECOVERY: 'recuperação',
};

@Component({
  selector: 'ch-delivery-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      @if (delivery(); as d) {
        <div class="breadcrumb">
          <a routerLink="/deliveries">Entregas</a> /
          <span class="mono">{{ d.id.slice(0, 8) }}</span>
        </div>
        <div class="page-header">
          <div>
            <h1 class="row">
              Entrega para {{ d.destination_name }} <ch-status [status]="d.status" />
            </h1>
            <p class="subtitle">
              Evento
              <a [routerLink]="['/events', d.event_id]" class="mono">{{ d.external_event_id }}</a> ·
              endpoint {{ d.endpoint_name }}
            </p>
          </div>
          <div class="actions">
            @if (d.status === 'FAILED') {
              <button class="btn primary" (click)="replay(d)" [disabled]="busy()">
                <ch-icon name="replay" [size]="15" /> Reprocessar
              </button>
            }
            <button class="btn icon" (click)="load()" aria-label="Atualizar">
              <ch-icon name="refresh" [size]="16" />
            </button>
          </div>
        </div>

        <div class="grid grid-kpi">
          <ch-kpi
            label="Tentativas"
            [value]="d.attempt_count + ' / ' + d.max_attempts"
            icon="replay"
          />
          <ch-kpi
            label="Último HTTP"
            [value]="d.last_status_code ?? '—'"
            icon="zap"
            [tone]="
              d.last_status_code && d.last_status_code < 300
                ? 'success'
                : d.last_status_code
                  ? 'danger'
                  : ''
            "
          />
          <ch-kpi label="Reprocessos manuais" [value]="d.replay_count" icon="shield" />
          <ch-kpi
            label="Próxima tentativa"
            [value]="
              d.status === 'RETRYING' ? ((d.next_attempt_at | date: 'HH:mm:ss') ?? '—') : '—'
            "
            icon="clock"
            tone="warning"
          />
        </div>

        @if (d.last_error && d.status !== 'SUCCEEDED') {
          <div class="alert danger mt-2"><b>Último erro:</b> {{ d.last_error }}</div>
        }

        <div class="grid grid-2 mt-2">
          <div class="card">
            <div class="card-header">
              <h2>Linha do tempo das tentativas</h2>
              <span class="hint">backoff exponencial com jitter</span>
            </div>
            <div class="card-body">
              @if (d.attempts.length === 0) {
                <ch-empty
                  icon="clock"
                  title="Aguardando a primeira tentativa"
                  message="A mensagem está no outbox/fila e será processada pelo worker."
                />
              } @else {
                <ol class="timeline">
                  @for (a of d.attempts; track a.id) {
                    <li [class]="a.outcome">
                      <div class="t-dot"></div>
                      <div class="t-body">
                        <div class="row" style="justify-content:space-between">
                          <div class="row" style="gap:8px">
                            <b>Tentativa #{{ a.attempt_number }}</b>
                            <ch-status [status]="a.outcome" />
                            <ch-http-code [code]="a.status_code" />
                            <span class="badge plain">{{ trigger(a.trigger) }}</span>
                          </div>
                          <span class="faint small">{{
                            a.started_at | date: 'dd/MM HH:mm:ss.SSS'
                          }}</span>
                        </div>
                        <div class="small muted mt-1">
                          {{ a.request_method }} <code>{{ a.request_url }}</code>
                          @if (a.duration_ms !== null) {
                            · {{ a.duration_ms }} ms
                          }
                        </div>
                        @if (a.error_message) {
                          <div class="small t-error">
                            <code>{{ a.error_type }}</code> — {{ a.error_message }}
                          </div>
                        }
                        @if (a.next_retry_at) {
                          <div class="small faint">
                            Retentativa agendada para {{ a.next_retry_at | date: 'HH:mm:ss' }}
                          </div>
                        }
                        @if (a.response_excerpt) {
                          <details class="small">
                            <summary>Resposta do destino</summary>
                            <pre class="code-block mt-1">{{ a.response_excerpt }}</pre>
                          </details>
                        }
                      </div>
                    </li>
                  }
                </ol>
              }
            </div>
          </div>
          <div class="stack">
            <div class="card">
              <div class="card-header">
                <h2>Payload enviado</h2>
                <span class="hint">{{
                  d.transform_rule_id ? 'após transformação' : 'original'
                }}</span>
              </div>
              <div class="card-body">
                @if (d.transformed_payload === null) {
                  <p class="faint small" style="margin:0">Disponível após a primeira tentativa.</p>
                } @else {
                  <ch-json [value]="d.transformed_payload" />
                }
              </div>
            </div>
            <div class="card">
              <div class="card-header"><h2>Garantias</h2></div>
              <div class="card-body small muted">
                Header <code>Idempotency-Key: {{ d.id }}</code> é enviado em todas as tentativas,
                permitindo que o destino deduplique efeitos. A entrega é <b>at-least-once</b>: o
                destino pode receber o mesmo evento mais de uma vez em caso de timeout após
                processamento.
              </div>
            </div>
          </div>
        </div>
      } @else {
        <div class="card"><ch-loading [rows]="6" /></div>
      }
    </div>
  `,
  styles: [
    `
      .timeline {
        list-style: none;
        margin: 0;
        padding: 0;
        position: relative;
      }
      .timeline li {
        display: flex;
        gap: 14px;
        padding-bottom: 18px;
        position: relative;
      }
      .timeline li::before {
        content: '';
        position: absolute;
        left: 6px;
        top: 16px;
        bottom: 0;
        width: 2px;
        background: var(--ch-border);
      }
      .timeline li:last-child::before {
        display: none;
      }
      .t-dot {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        margin-top: 3px;
        flex-shrink: 0;
        background: var(--ch-text-3);
        box-shadow: 0 0 0 4px var(--ch-surface);
        z-index: 1;
      }
      li.SUCCESS .t-dot {
        background: var(--ch-success);
      }
      li.RETRYABLE_ERROR .t-dot {
        background: var(--ch-warning);
      }
      li.PERMANENT_ERROR .t-dot {
        background: var(--ch-danger);
      }
      li.IN_PROGRESS .t-dot {
        background: var(--ch-info);
      }
      .t-body {
        flex: 1;
        min-width: 0;
      }
      .t-error {
        color: var(--ch-danger);
        margin-top: 4px;
      }
      details summary {
        cursor: pointer;
        color: var(--ch-text-2);
        margin-top: 6px;
      }
    `,
  ],
})
export class DeliveryDetailComponent implements OnInit {
  readonly id = input.required<string>();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly router = inject(Router);

  readonly delivery = signal<DeliveryDetail | null>(null);
  readonly busy = signal(false);

  constructor() {
    startPolling(() => {
      const s = this.delivery()?.status;
      if (s && s !== 'SUCCEEDED' && s !== 'FAILED') this.load();
    }, 2500);
  }

  ngOnInit(): void {
    this.load();
  }

  trigger(t: string): string {
    return TRIGGER_LABEL[t] ?? t;
  }

  load(): void {
    this.api.delivery(this.auth.orgId(), this.id()).subscribe({
      next: (d) => this.delivery.set(d),
      error: (err: unknown) => {
        this.toast.error(err);
        void this.router.navigate(['/deliveries']);
      },
    });
  }

  async replay(d: DeliveryDetail): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Reprocessar entrega',
      message:
        'A entrega receberá um novo ciclo de tentativas. A ação fica registrada na auditoria.',
      confirmLabel: 'Reprocessar',
    });
    if (!ok) return;
    this.busy.set(true);
    this.api.replayDelivery(this.auth.orgId(), d.id).subscribe({
      next: () => {
        this.busy.set(false);
        this.toast.success('Entrega reenfileirada.');
        this.load();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.toast.error(err);
      },
    });
  }
}
