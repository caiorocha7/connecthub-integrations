import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import { SimulatorControl, SimulatorMode, SimulatorRequests } from '../../core/models';
import { startPolling } from '../../core/polling';
import { SimulatorService } from '../../core/simulator.service';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

interface ModeOption {
  mode: SimulatorMode;
  title: string;
  description: string;
  icon: string;
}

@Component({
  selector: 'ch-simulator',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Simulador de falhas</h1>
          <p class="subtitle">
            Destino HTTP controlável em <code>http://simulator:8131/hooks/&lt;nome&gt;</code> para
            demonstrar retentativas, timeouts, rate limit e recuperação.
          </p>
        </div>
        <div class="actions">
          <button class="btn" (click)="clear()">
            <ch-icon name="trash" [size]="15" /> Limpar requisições
          </button>
          <button class="btn" (click)="reset()">
            <ch-icon name="refresh" [size]="15" /> Restaurar padrão
          </button>
        </div>
      </div>

      @if (unavailable()) {
        <div class="alert warning">
          Simulador indisponível. Verifique se o serviço <code>simulator</code> está em execução
          (<code>docker compose ps</code>).
        </div>
      }

      <div class="grid modes">
        @for (o of options; track o.mode) {
          <button
            class="card mode"
            [class.active]="control()?.mode === o.mode"
            (click)="apply(o.mode)"
          >
            <span class="mode-icon {{ o.mode }}"><ch-icon [name]="o.icon" [size]="18" /></span>
            <b>{{ o.title }}</b>
            <span class="small muted">{{ o.description }}</span>
            @if (control()?.mode === o.mode) {
              <span class="badge success pulse">ativo</span>
            }
          </button>
        }
      </div>

      <div class="grid grid-2 mt-2">
        <div class="card">
          <div class="card-header">
            <h2>Requisições recebidas</h2>
            @if (requests(); as r) {
              <span class="hint"
                >{{ r.total_received }} recebidas · {{ r.succeeded }} com 2xx ·
                {{ r.unique_successful_deliveries }} entregas únicas</span
              >
            }
          </div>
          <div class="card-body flush">
            @if (!requests()?.items?.length) {
              <ch-empty
                icon="simulator"
                title="Nenhuma requisição ainda"
                message="Envie um webhook para um endpoint roteado ao simulador."
              />
            } @else {
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th>Horário</th>
                      <th>Hook</th>
                      <th>Event ID</th>
                      <th>Tentativa</th>
                      <th>Modo</th>
                      <th>Resposta</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (req of requests()!.items; track req.id) {
                      <tr
                        class="clickable"
                        (click)="selected.set(req.id === selected() ? null : req.id)"
                      >
                        <td class="nowrap">{{ req.received_at | date: 'HH:mm:ss.SSS' }}</td>
                        <td>
                          <code>{{ req.hook }}</code>
                        </td>
                        <td>
                          <code class="truncate" style="max-width:160px">{{
                            req.headers['x-connecthub-event-id'] || '—'
                          }}</code>
                        </td>
                        <td>{{ req.headers['x-connecthub-attempt'] || '—' }}</td>
                        <td>
                          <span class="badge plain">{{ req.mode }}</span>
                        </td>
                        <td>
                          @if (req.response_status === null) {
                            <span class="badge plain info">timeout</span>
                          } @else {
                            <ch-http-code [code]="req.response_status" />
                          }
                        </td>
                      </tr>
                      @if (selected() === req.id) {
                        <tr>
                          <td colspan="6">
                            <ch-json [value]="{ headers: req.headers, body: req.body }" />
                          </td>
                        </tr>
                      }
                    }
                  </tbody>
                </table>
              </div>
            }
          </div>
        </div>

        <div class="card">
          <div class="card-header"><h2>Parâmetros</h2></div>
          <form
            class="card-body"
            [formGroup]="form"
            (ngSubmit)="apply(control()?.mode ?? 'normal')"
          >
            <div class="field">
              <label for="s-code">Status HTTP do modo erro</label>
              <select id="s-code" class="input" formControlName="status_code">
                <option [ngValue]="500">500 Internal Server Error</option>
                <option [ngValue]="502">502 Bad Gateway</option>
                <option [ngValue]="503">503 Service Unavailable</option>
                <option [ngValue]="504">504 Gateway Timeout</option>
              </select>
            </div>
            <div class="field">
              <label for="s-delay">Atraso do modo timeout (s)</label>
              <input
                id="s-delay"
                class="input"
                type="number"
                min="0"
                max="120"
                formControlName="delay_seconds"
              />
              <span class="help"
                >Use um valor maior que o timeout do destino para forçar erro de timeout.</span
              >
            </div>
            <div class="field">
              <label for="s-ra">Retry-After do modo 429 (s)</label>
              <input
                id="s-ra"
                class="input"
                type="number"
                min="0"
                max="3600"
                formControlName="retry_after"
              />
            </div>
            <div class="field">
              <label for="s-fail">Falhar apenas as próximas N requisições</label>
              <input
                id="s-fail"
                class="input"
                type="number"
                min="1"
                max="1000"
                formControlName="fail_next"
                placeholder="vazio = até restaurar"
              />
              @if (
                control()?.remaining_failures !== null &&
                control()?.remaining_failures !== undefined
              ) {
                <span class="help"
                  >Restam {{ control()?.remaining_failures }} falha(s) antes de voltar ao
                  normal.</span
                >
              }
            </div>
            <button class="btn primary" type="submit" [disabled]="form.invalid">
              Aplicar ao modo atual
            </button>
          </form>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
      .modes {
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      }
      .mode {
        text-align: left;
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 6px;
        cursor: pointer;
        font: inherit;
        color: inherit;
        transition:
          border-color 0.15s,
          box-shadow 0.15s;
      }
      .mode:hover {
        border-color: var(--ch-primary);
      }
      .mode.active {
        border-color: var(--ch-primary);
        box-shadow: 0 0 0 3px rgba(91, 91, 240, 0.15);
      }
      .mode .badge {
        align-self: flex-start;
      }
      .mode-icon {
        width: 34px;
        height: 34px;
        border-radius: 9px;
        display: grid;
        place-items: center;
        background: var(--ch-success-50);
        color: var(--ch-success);
      }
      .mode-icon.error {
        background: var(--ch-danger-50);
        color: var(--ch-danger);
      }
      .mode-icon.timeout {
        background: var(--ch-info-50);
        color: var(--ch-info);
      }
      .mode-icon.rate_limit {
        background: var(--ch-warning-50);
        color: var(--ch-warning);
      }
    `,
  ],
})
export class SimulatorComponent {
  private readonly sim = inject(SimulatorService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder);

  readonly options: ModeOption[] = [
    {
      mode: 'normal',
      title: 'Operação normal',
      description: 'Responde 200 OK imediatamente.',
      icon: 'check',
    },
    {
      mode: 'error',
      title: 'Erro 5xx',
      description: 'Responde com o status 5xx configurado.',
      icon: 'failures',
    },
    {
      mode: 'timeout',
      title: 'Timeout',
      description: 'Segura a resposta além do timeout do destino.',
      icon: 'clock',
    },
    {
      mode: 'rate_limit',
      title: 'Rate limit (429)',
      description: 'Responde 429 com header Retry-After.',
      icon: 'pause',
    },
  ];

  readonly control = signal<SimulatorControl | null>(null);
  readonly requests = signal<SimulatorRequests | null>(null);
  readonly unavailable = signal(false);
  readonly selected = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    status_code: [500],
    delay_seconds: [30, [Validators.min(0), Validators.max(120)]],
    retry_after: [5, [Validators.min(0), Validators.max(3600)]],
    fail_next: [null as number | null, [Validators.min(1), Validators.max(1000)]],
  });

  constructor() {
    this.refresh(true);
    startPolling(() => this.refresh(false), 2000);
  }

  refresh(syncForm: boolean): void {
    this.sim.control().subscribe({
      next: (c) => {
        this.control.set(c);
        this.unavailable.set(false);
        if (syncForm) {
          this.form.patchValue({
            status_code: c.status_code,
            delay_seconds: c.delay_seconds,
            retry_after: c.retry_after,
            fail_next: c.fail_next,
          });
        }
      },
      error: () => this.unavailable.set(true),
    });
    this.sim
      .requests(50)
      .subscribe({ next: (r) => this.requests.set(r), error: () => this.unavailable.set(true) });
  }

  apply(mode: SimulatorMode): void {
    const v = this.form.getRawValue();
    this.sim.setControl({ mode, ...v, fail_next: v.fail_next || null }).subscribe({
      next: (c) => {
        this.control.set(c);
        this.toast.success(
          `Simulador em modo "${this.options.find((o) => o.mode === mode)?.title}".`,
        );
      },
      error: (err: unknown) => this.toast.error(err, 'Não foi possível alterar o simulador.'),
    });
  }

  reset(): void {
    this.sim.reset().subscribe({
      next: () => {
        this.toast.success('Simulador restaurado e histórico limpo.');
        this.refresh(true);
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  clear(): void {
    this.sim.clear().subscribe({
      next: () => this.refresh(false),
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
