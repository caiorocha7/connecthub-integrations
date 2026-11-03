import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Destination, Endpoint, RouteInfo, TransformRule } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-endpoint-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      @if (endpoint(); as ep) {
        <div class="breadcrumb"><a routerLink="/endpoints">Endpoints</a> / {{ ep.name }}</div>
        <div class="page-header">
          <div>
            <h1>{{ ep.name }}</h1>
            <p class="subtitle">{{ ep.description || 'Sem descrição' }}</p>
          </div>
          <div class="actions">
            <a class="btn" [routerLink]="['/events']" [queryParams]="{ endpoint_id: ep.id }"
              ><ch-icon name="events" [size]="15" /> Ver eventos</a
            >
            @if (auth.isAdmin()) {
              <label class="row small" style="gap:8px">
                <span class="switch"
                  ><input
                    type="checkbox"
                    [checked]="ep.is_active"
                    (change)="toggleActive(ep)" /><span></span
                ></span>
                {{ ep.is_active ? 'Ativo' : 'Inativo' }}
              </label>
              <button class="btn danger" (click)="remove(ep)">
                <ch-icon name="trash" [size]="15" /> Excluir
              </button>
            }
          </div>
        </div>

        <div class="grid grid-2">
          <div class="stack">
            <div class="card">
              <div class="card-header">
                <h2>Recebimento</h2>
                <span class="hint">rota pública, sem login humano</span>
              </div>
              <div class="card-body">
                <div class="field">
                  <label>URL de ingestão (POST, application/json)</label>
                  <div class="copy-field">
                    <code>{{ ep.ingest_url }}</code
                    ><ch-copy [value]="ep.ingest_url" />
                  </div>
                </div>
                <div class="field">
                  <label>Segredo de assinatura</label>
                  <div class="copy-field">
                    <code>{{ revealed() ?? ep.secret_preview }}</code>
                    @if (revealed()) {
                      <ch-copy [value]="revealed()!" />
                    }
                    @if (auth.isAdmin() && !revealed()) {
                      <button class="btn sm" (click)="reveal(ep)">
                        <ch-icon name="eye" [size]="14" /> Revelar
                      </button>
                    }
                  </div>
                  <span class="help">
                    @if (ep.secret_rotated_at) {
                      Rotacionado em {{ ep.secret_rotated_at | date: 'dd/MM/yyyy HH:mm' }}.
                    }
                    @if (ep.previous_secret_expires_at) {
                      Segredo anterior aceito até
                      {{ ep.previous_secret_expires_at | date: 'dd/MM/yyyy HH:mm' }}.
                    }
                  </span>
                </div>
                @if (auth.isAdmin()) {
                  <div class="row">
                    <select class="input sm" style="width:auto" #grace>
                      <option value="60">Manter o anterior por 1h</option>
                      <option value="1440">Manter o anterior por 24h</option>
                      <option value="0">Invalidar o anterior imediatamente</option>
                    </select>
                    <button class="btn sm" (click)="rotate(ep, +grace.value)">
                      <ch-icon name="key" [size]="14" /> Rotacionar segredo
                    </button>
                  </div>
                }
              </div>
            </div>

            <div class="card">
              <div class="card-header">
                <h2>Destinos associados</h2>
                <span class="hint">cada evento gera uma entrega lógica por rota ativa</span>
              </div>
              <div class="card-body flush">
                @if (ep.routes.length === 0) {
                  <ch-empty
                    icon="destination"
                    title="Sem destinos"
                    message="Eventos recebidos sem rota ativa são marcados como 'Sem rota'."
                  />
                } @else {
                  <div class="table-wrap">
                    <table class="table">
                      <thead>
                        <tr>
                          <th>Destino</th>
                          <th>Transformação</th>
                          <th>Ativa</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (r of ep.routes; track r.id) {
                          <tr>
                            <td>
                              <b>{{ r.destination_name }}</b>
                            </td>
                            <td>
                              @if (auth.isAdmin()) {
                                <select
                                  class="input sm"
                                  [value]="r.transform_rule_id ?? ''"
                                  (change)="setRule(ep, r, $event)"
                                >
                                  <option value="">Payload original</option>
                                  @for (rule of rules(); track rule.id) {
                                    <option [value]="rule.id">{{ rule.name }}</option>
                                  }
                                </select>
                              } @else {
                                {{ r.transform_rule_name ?? 'Payload original' }}
                              }
                            </td>
                            <td>
                              <span class="switch">
                                <input
                                  type="checkbox"
                                  [checked]="r.is_active"
                                  [disabled]="!auth.isAdmin()"
                                  (change)="toggleRoute(ep, r)"
                                /><span></span>
                              </span>
                            </td>
                            <td class="actions-cell">
                              @if (auth.isAdmin()) {
                                <button
                                  class="btn sm ghost icon danger"
                                  (click)="removeRoute(ep, r)"
                                  aria-label="Remover rota"
                                >
                                  <ch-icon name="trash" [size]="14" />
                                </button>
                              }
                            </td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                }
                @if (auth.isAdmin()) {
                  <form class="route-form" [formGroup]="routeForm" (ngSubmit)="addRoute(ep)">
                    <select class="input sm" formControlName="destination_id" aria-label="Destino">
                      <option value="">Selecione um destino…</option>
                      @for (d of availableDestinations(); track d.id) {
                        <option [value]="d.id">
                          {{ d.name }}{{ d.is_active ? '' : ' (inativo)' }}
                        </option>
                      }
                    </select>
                    <select
                      class="input sm"
                      formControlName="transform_rule_id"
                      aria-label="Transformação"
                    >
                      <option value="">Sem transformação</option>
                      @for (rule of rules(); track rule.id) {
                        <option [value]="rule.id">{{ rule.name }}</option>
                      }
                    </select>
                    <button class="btn sm primary" type="submit" [disabled]="routeForm.invalid">
                      <ch-icon name="plus" [size]="14" /> Associar
                    </button>
                  </form>
                  @if (destinations().length === 0) {
                    <p class="small faint" style="padding:0 20px 16px">
                      Nenhum destino cadastrado. <a routerLink="/destinations">Criar destino</a>.
                    </p>
                  }
                }
              </div>
            </div>
          </div>

          <div class="stack">
            @if (auth.isAdmin()) {
              <div class="card">
                <div class="card-header"><h2>Configuração</h2></div>
                <form class="card-body" [formGroup]="editForm" (ngSubmit)="save(ep)">
                  <div class="field">
                    <label for="name">Nome</label>
                    <input id="name" class="input" formControlName="name" />
                  </div>
                  <div class="field">
                    <label for="desc">Descrição</label>
                    <input id="desc" class="input" formControlName="description" />
                  </div>
                  <div class="field">
                    <label for="path">Caminho do ID do evento</label>
                    <input id="path" class="input mono" formControlName="event_id_path" />
                  </div>
                  <button
                    class="btn primary"
                    type="submit"
                    [disabled]="editForm.invalid || editForm.pristine"
                  >
                    Salvar
                  </button>
                </form>
              </div>
            }
            <div class="card">
              <div class="card-header">
                <h2>Como enviar</h2>
                <span class="hint">HMAC-SHA256 de "timestamp.corpo"</span>
              </div>
              <div class="card-body">
                <p class="small muted" style="margin-top:0">
                  Assine <code>{{ '{timestamp}.{corpo_bruto}' }}</code> com o segredo e envie os
                  headers <code>X-ConnectHub-Timestamp</code>,
                  <code>X-ConnectHub-Signature: v1=&lt;hex&gt;</code> e, opcionalmente,
                  <code>X-ConnectHub-Event-Id</code>. Requisições com mais de 5 min são rejeitadas
                  (anti-replay).
                </p>
                <pre class="code-block">{{ snippet() }}</pre>
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
      .route-form {
        display: flex;
        gap: 8px;
        padding: 14px 20px;
        border-top: 1px solid var(--ch-border);
        flex-wrap: wrap;
      }
      .route-form select {
        flex: 1;
        min-width: 160px;
      }
    `,
  ],
})
export class EndpointDetailComponent implements OnInit {
  readonly id = input.required<string>();
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  readonly endpoint = signal<Endpoint | null>(null);
  readonly destinations = signal<Destination[]>([]);
  readonly rules = signal<TransformRule[]>([]);
  readonly revealed = signal<string | null>(null);

  readonly availableDestinations = computed(() => {
    const used = new Set(this.endpoint()?.routes.map((r) => r.destination_id) ?? []);
    return this.destinations().filter((d) => !used.has(d.id));
  });

  readonly snippet = computed(() => {
    const ep = this.endpoint();
    if (!ep) return '';
    return [
      `SECRET='<segredo>'`,
      `BODY='{"id":"ord_1001","type":"order.paid","data":{"total":"259.90"}}'`,
      `TS=$(date +%s)`,
      `SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" | sed 's/^.* //')`,
      ``,
      `curl -X POST '${ep.ingest_url}' \\`,
      `  -H 'Content-Type: application/json' \\`,
      `  -H "X-ConnectHub-Timestamp: $TS" \\`,
      `  -H "X-ConnectHub-Signature: v1=$SIG" \\`,
      `  -H 'X-ConnectHub-Event-Id: ord_1001' \\`,
      `  -d "$BODY"`,
    ].join('\n');
  });

  readonly editForm = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2)]],
    description: [''],
    event_id_path: ['', [Validators.required, Validators.pattern(/^[A-Za-z0-9_\-.[\]$]{1,200}$/)]],
  });

  readonly routeForm = this.fb.nonNullable.group({
    destination_id: ['', Validators.required],
    transform_rule_id: [''],
  });

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    const org = this.auth.orgId();
    forkJoin({
      ep: this.api.endpoint(org, this.id()),
      destinations: this.api.destinations(org),
      rules: this.api.rules(org),
    }).subscribe({
      next: ({ ep, destinations, rules }) => {
        this.setEndpoint(ep);
        this.destinations.set(destinations);
        this.rules.set(rules);
      },
      error: (err: unknown) => {
        this.toast.error(err);
        void this.router.navigate(['/endpoints']);
      },
    });
  }

  private setEndpoint(ep: Endpoint): void {
    this.endpoint.set(ep);
    this.editForm.reset({
      name: ep.name,
      description: ep.description ?? '',
      event_id_path: ep.event_id_path,
    });
  }

  private refresh(): void {
    this.api.endpoint(this.auth.orgId(), this.id()).subscribe((ep) => this.setEndpoint(ep));
  }

  save(ep: Endpoint): void {
    const v = this.editForm.getRawValue();
    this.api
      .updateEndpoint(this.auth.orgId(), ep.id, { ...v, description: v.description || null })
      .subscribe({
        next: (updated) => {
          this.setEndpoint(updated);
          this.toast.success('Endpoint atualizado.');
        },
        error: (err: unknown) => this.toast.error(err),
      });
  }

  toggleActive(ep: Endpoint): void {
    this.api.updateEndpoint(this.auth.orgId(), ep.id, { is_active: !ep.is_active }).subscribe({
      next: (updated) => {
        this.setEndpoint(updated);
        this.toast.success(
          updated.is_active
            ? 'Endpoint ativado.'
            : 'Endpoint desativado: novos webhooks serão recusados.',
        );
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  reveal(ep: Endpoint): void {
    this.api.revealSecret(this.auth.orgId(), ep.id).subscribe({
      next: (s) => this.revealed.set(s.signing_secret),
      error: (err: unknown) => this.toast.error(err),
    });
  }

  async rotate(ep: Endpoint, graceMinutes: number): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Rotacionar segredo',
      message:
        graceMinutes > 0
          ? `Um novo segredo será gerado. O atual continuará válido por ${graceMinutes >= 60 ? graceMinutes / 60 + 'h' : graceMinutes + ' min'}.`
          : 'Um novo segredo será gerado e o atual deixará de ser aceito imediatamente.',
      confirmLabel: 'Rotacionar',
    });
    if (!ok) return;
    this.api.rotateSecret(this.auth.orgId(), ep.id, graceMinutes).subscribe({
      next: (s) => {
        this.revealed.set(s.signing_secret);
        this.toast.success('Novo segredo gerado. Atualize o sistema de origem.');
        this.refresh();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  addRoute(ep: Endpoint): void {
    const v = this.routeForm.getRawValue();
    this.api
      .createRoute(this.auth.orgId(), ep.id, {
        destination_id: v.destination_id,
        transform_rule_id: v.transform_rule_id || null,
      })
      .subscribe({
        next: () => {
          this.routeForm.reset({ destination_id: '', transform_rule_id: '' });
          this.toast.success('Destino associado.');
          this.refresh();
        },
        error: (err: unknown) => this.toast.error(err),
      });
  }

  setRule(ep: Endpoint, route: RouteInfo, event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    const body = value ? { transform_rule_id: value } : { clear_transform: true };
    this.api.updateRoute(this.auth.orgId(), ep.id, route.id, body).subscribe({
      next: () => {
        this.toast.success('Transformação da rota atualizada.');
        this.refresh();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  toggleRoute(ep: Endpoint, route: RouteInfo): void {
    this.api
      .updateRoute(this.auth.orgId(), ep.id, route.id, { is_active: !route.is_active })
      .subscribe({
        next: () => this.refresh(),
        error: (err: unknown) => this.toast.error(err),
      });
  }

  async removeRoute(ep: Endpoint, route: RouteInfo): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Remover rota',
      message: `Novos eventos deixarão de ser entregues a "${route.destination_name}". O histórico é preservado.`,
      confirmLabel: 'Remover',
      danger: true,
    });
    if (!ok) return;
    this.api.deleteRoute(this.auth.orgId(), ep.id, route.id).subscribe({
      next: () => this.refresh(),
      error: (err: unknown) => this.toast.error(err),
    });
  }

  async remove(ep: Endpoint): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Excluir endpoint',
      message: `Excluir "${ep.name}"? Endpoints com histórico de eventos não podem ser excluídos — desative-os.`,
      confirmLabel: 'Excluir',
      danger: true,
    });
    if (!ok) return;
    this.api.deleteEndpoint(this.auth.orgId(), ep.id).subscribe({
      next: () => {
        this.toast.success('Endpoint excluído.');
        void this.router.navigate(['/endpoints']);
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
