import { DatePipe, DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { DashboardSummary, DeliverySummary } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import {
  ChartSeries,
  DonutChartComponent,
  DonutSlice,
  LineChartComponent,
} from '../../shared/charts';
import { SHARED_UI } from '../../shared/ui';

const REFRESH_MS = 10_000;

@Component({
  selector: 'ch-dashboard',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    DatePipe,
    DecimalPipe,
    LineChartComponent,
    DonutChartComponent,
    ...SHARED_UI,
  ],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Visão geral</h1>
          <p class="subtitle">
            Saúde das integrações de <b>{{ auth.currentMembership()?.organization_name }}</b>
            @if (lastUpdated()) {
              · <span class="faint">atualizado às {{ lastUpdated() | date: 'HH:mm:ss' }}</span>
            }
          </p>
        </div>
        <div class="actions">
          <div class="segmented" role="group" aria-label="Período">
            @for (p of periods; track p.hours) {
              <button [class.active]="hours() === p.hours" (click)="setPeriod(p.hours)">
                {{ p.label }}
              </button>
            }
          </div>
          <button
            class="btn"
            (click)="autoRefresh.set(!autoRefresh())"
            [title]="'Atualização automática a cada 10s'"
          >
            <ch-icon [name]="autoRefresh() ? 'pause' : 'play'" [size]="15" />
            {{ autoRefresh() ? 'Ao vivo' : 'Pausado' }}
          </button>
          <button class="btn icon" (click)="load()" aria-label="Atualizar">
            <ch-icon name="refresh" [size]="16" />
          </button>
        </div>
      </div>

      @if (!data() && loading()) {
        <div class="card"><ch-loading [rows]="6" /></div>
      } @else if (data(); as d) {
        <div class="grid grid-kpi">
          <ch-kpi
            label="Eventos recebidos"
            [value]="d.events_received"
            icon="events"
            [hint]="periodLabel()"
          />
          <ch-kpi
            label="Entregas com sucesso"
            [value]="d.deliveries_succeeded"
            icon="check"
            tone="success"
          />
          <ch-kpi
            label="Entregas com falha"
            [value]="d.deliveries_failed"
            icon="failures"
            tone="danger"
            hint="esgotaram tentativas"
          />
          <ch-kpi
            label="Pendentes / em retry"
            [value]="d.deliveries_pending"
            icon="clock"
            tone="warning"
            [hint]="d.deliveries_retrying + ' aguardando retentativa'"
          />
          <ch-kpi
            label="Taxa de sucesso"
            [value]="d.success_rate === null ? '—' : (d.success_rate | number: '1.0-1') + '%'"
            icon="zap"
            tone="accent"
            hint="entre entregas finalizadas"
          />
          <ch-kpi
            label="Duplicados bloqueados"
            [value]="d.duplicates_blocked"
            icon="shield"
            hint="idempotência"
          />
        </div>

        <div class="grid grid-2 mt-2">
          <div class="card">
            <div class="card-header">
              <h2>Fluxo de eventos e entregas</h2>
              <span class="hint">por {{ d.period_hours <= 72 ? 'hora' : 'dia' }}</span>
            </div>
            <div class="card-body">
              <ch-line-chart
                [series]="series()"
                [labels]="labels()"
                ariaLabel="Eventos recebidos e entregas por período"
              />
            </div>
          </div>
          <div class="card">
            <div class="card-header"><h2>Estado das entregas</h2></div>
            <div class="card-body">
              <ch-donut
                [slices]="slices()"
                [centerValue]="'' + d.deliveries_total"
                centerLabel="entregas"
              />
              <div class="divider"></div>
              <dl class="kv small">
                <dt>Latência média</dt>
                <dd>
                  {{
                    d.avg_attempt_duration_ms === null
                      ? '—'
                      : (d.avg_attempt_duration_ms | number: '1.0-0') + ' ms'
                  }}
                </dd>
                <dt>Outbox pendente</dt>
                <dd>
                  <span
                    class="badge plain"
                    [class.warning]="d.outbox_pending > 0"
                    [class.success]="d.outbox_pending === 0"
                  >
                    {{ d.outbox_pending }} mensagem(ns)
                  </span>
                </dd>
              </dl>
            </div>
          </div>
        </div>

        <div class="grid grid-half mt-2">
          <div class="card">
            <div class="card-header">
              <h2>Saúde por destino</h2>
              <a routerLink="/destinations" class="small">Gerenciar</a>
            </div>
            <div class="card-body flush">
              @if (d.destinations.length === 0) {
                <ch-empty
                  icon="destination"
                  title="Nenhum destino"
                  message="Cadastre um destino HTTP para começar a entregar eventos."
                />
              } @else {
                <div class="table-wrap">
                  <table class="table">
                    <thead>
                      <tr>
                        <th>Destino</th>
                        <th>Sucesso</th>
                        <th>Falha</th>
                        <th>Pend.</th>
                        <th style="width:30%">Taxa</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (h of d.destinations; track h.destination_id) {
                        <tr>
                          <td>
                            <b>{{ h.destination_name }}</b>
                          </td>
                          <td>{{ h.succeeded }}</td>
                          <td [class.text-danger]="h.failed > 0">{{ h.failed }}</td>
                          <td>{{ h.pending }}</td>
                          <td>
                            @if (h.success_rate === null) {
                              <span class="faint small">sem dados</span>
                            } @else {
                              <div class="bar">
                                <span
                                  [style.width.%]="h.success_rate"
                                  [class.low]="h.success_rate < 80"
                                ></span>
                              </div>
                              <span class="small">{{ h.success_rate | number: '1.0-1' }}%</span>
                            }
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              }
            </div>
          </div>

          <div class="card">
            <div class="card-header">
              <h2>Falhas recentes</h2>
              <a routerLink="/failures" class="small">Ver todas</a>
            </div>
            <div class="card-body flush">
              @if (d.recent_failures.length === 0) {
                <ch-empty
                  icon="check"
                  title="Tudo certo por aqui"
                  message="Nenhuma entrega com falha ou aguardando retentativa."
                />
              } @else {
                <ul class="failures">
                  @for (f of d.recent_failures; track f.id) {
                    <li>
                      <div class="f-main">
                        <a [routerLink]="['/deliveries', f.id]" class="mono">{{
                          f.external_event_id
                        }}</a>
                        <span class="faint small"
                          >→ {{ f.destination_name }} · tentativa {{ f.attempt_count }}/{{
                            f.max_attempts
                          }}</span
                        >
                        <span class="small f-err">{{ f.last_error || 'sem detalhes' }}</span>
                      </div>
                      <div class="row">
                        <ch-status [status]="f.status" />
                        @if (f.status === 'FAILED') {
                          <button
                            class="btn sm"
                            (click)="replay(f)"
                            [disabled]="replaying() === f.id"
                          >
                            <ch-icon name="replay" [size]="14" /> Reprocessar
                          </button>
                        }
                      </div>
                    </li>
                  }
                </ul>
              }
            </div>
          </div>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .segmented {
        display: inline-flex;
        background: var(--ch-surface);
        border: 1px solid var(--ch-border);
        border-radius: 8px;
        padding: 3px;
      }
      .segmented button {
        border: none;
        background: none;
        padding: 5px 12px;
        border-radius: 6px;
        font: inherit;
        font-weight: 550;
        color: var(--ch-text-2);
        cursor: pointer;
      }
      .segmented button.active {
        background: var(--ch-primary-50);
        color: var(--ch-primary);
      }
      .bar {
        height: 6px;
        background: var(--ch-neutral-50);
        border-radius: 6px;
        overflow: hidden;
        margin-bottom: 2px;
      }
      .bar span {
        display: block;
        height: 100%;
        background: var(--ch-accent);
        border-radius: 6px;
      }
      .bar span.low {
        background: var(--ch-warning);
      }
      .text-danger {
        color: var(--ch-danger);
        font-weight: 600;
      }
      .failures {
        list-style: none;
        margin: 0;
        padding: 0;
      }
      .failures li {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        padding: 12px 20px;
        border-bottom: 1px solid var(--ch-border);
        align-items: center;
      }
      .failures li:last-child {
        border-bottom: none;
      }
      .f-main {
        display: flex;
        flex-direction: column;
        min-width: 0;
      }
      .f-err {
        color: var(--ch-danger);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        max-width: 360px;
      }
    `,
  ],
})
export class DashboardComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);

  readonly periods = [
    { hours: 24, label: '24h' },
    { hours: 24 * 7, label: '7 dias' },
    { hours: 24 * 30, label: '30 dias' },
  ];
  readonly hours = signal(24);
  readonly data = signal<DashboardSummary | null>(null);
  readonly loading = signal(false);
  readonly lastUpdated = signal<Date | null>(null);
  readonly autoRefresh = signal(true);
  readonly replaying = signal<string | null>(null);

  readonly periodLabel = computed(
    () => this.periods.find((p) => p.hours === this.hours())?.label ?? '',
  );

  readonly labels = computed(() =>
    (this.data()?.timeline ?? []).map((b) => {
      const d = new Date(b.bucket);
      return this.hours() <= 72
        ? `${String(d.getHours()).padStart(2, '0')}h`
        : `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}`;
    }),
  );

  readonly series = computed<ChartSeries[]>(() => {
    const t = this.data()?.timeline ?? [];
    return [
      { label: 'Recebidos', color: '#5b5bf0', values: t.map((b) => b.received) },
      { label: 'Entregues', color: '#14b8a6', values: t.map((b) => b.succeeded) },
      { label: 'Falhas', color: '#e11d48', values: t.map((b) => b.failed) },
    ];
  });

  readonly slices = computed<DonutSlice[]>(() => {
    const d = this.data();
    if (!d) return [];
    return [
      { label: 'Sucesso', value: d.deliveries_succeeded, color: '#16a34a' },
      { label: 'Em retry', value: d.deliveries_retrying, color: '#d97706' },
      { label: 'Pendente', value: d.deliveries_pending - d.deliveries_retrying, color: '#5b5bf0' },
      { label: 'Falha', value: d.deliveries_failed, color: '#e11d48' },
    ];
  });

  constructor() {
    this.load();
    startPolling(() => {
      if (this.autoRefresh()) this.load(true);
    }, REFRESH_MS);
  }

  setPeriod(hours: number): void {
    this.hours.set(hours);
    this.load();
  }

  load(silent = false): void {
    if (!silent) this.loading.set(true);
    this.api.dashboard(this.auth.orgId(), this.hours()).subscribe({
      next: (d) => {
        this.data.set(d);
        this.loading.set(false);
        this.lastUpdated.set(new Date());
      },
      error: (err: unknown) => {
        this.loading.set(false);
        if (!silent) this.toast.error(err);
      },
    });
  }

  replay(f: DeliverySummary): void {
    this.replaying.set(f.id);
    this.api.replayDelivery(this.auth.orgId(), f.id).subscribe({
      next: () => {
        this.toast.success('Entrega reenfileirada para reprocessamento.');
        this.replaying.set(null);
        this.load(true);
      },
      error: (err: unknown) => {
        this.replaying.set(null);
        this.toast.error(err);
      },
    });
  }
}
