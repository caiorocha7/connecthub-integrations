import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Endpoint, EndpointWithSecret } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-endpoints',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Endpoints de entrada</h1>
          <p class="subtitle">
            URLs públicas que recebem webhooks assinados dos sistemas de origem.
          </p>
        </div>
        @if (auth.isAdmin()) {
          <div class="actions">
            <button class="btn primary" (click)="openCreate()">
              <ch-icon name="plus" [size]="16" /> Novo endpoint
            </button>
          </div>
        }
      </div>

      <div class="card">
        @if (loading()) {
          <ch-loading />
        } @else if (endpoints().length === 0) {
          <ch-empty
            icon="endpoint"
            title="Nenhum endpoint ainda"
            message="Crie um endpoint para obter uma URL de ingestão e um segredo de assinatura HMAC."
          >
            @if (auth.isAdmin()) {
              <button class="btn primary" (click)="openCreate()">
                <ch-icon name="plus" [size]="16" /> Criar endpoint
              </button>
            }
          </ch-empty>
        } @else {
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>URL de ingestão</th>
                  <th>Destinos</th>
                  <th>Status</th>
                  <th>Criado</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (e of endpoints(); track e.id) {
                  <tr class="clickable" (click)="open(e)">
                    <td>
                      <b>{{ e.name }}</b>
                      @if (e.description) {
                        <div class="faint small truncate">{{ e.description }}</div>
                      }
                    </td>
                    <td>
                      <code class="truncate" style="max-width:340px">{{ e.ingest_url }}</code>
                    </td>
                    <td>
                      @if (e.routes.length) {
                        <span class="badge plain primary">{{ e.routes.length }} rota(s)</span>
                      } @else {
                        <span class="badge plain warning">sem rota</span>
                      }
                    </td>
                    <td>
                      <span class="badge" [class.success]="e.is_active">{{
                        e.is_active ? 'Ativo' : 'Inativo'
                      }}</span>
                    </td>
                    <td class="faint"><ch-time [value]="e.created_at" /></td>
                    <td class="actions-cell" (click)="$event.stopPropagation()">
                      <ch-copy [value]="e.ingest_url" label="URL" />
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </div>

    @if (showCreate()) {
      <ch-modal title="Novo endpoint" (closed)="showCreate.set(false)">
        <form [formGroup]="form" (ngSubmit)="create()" id="create-endpoint" novalidate>
          <div class="field">
            <label for="ep-name">Nome</label>
            <input
              id="ep-name"
              class="input"
              formControlName="name"
              placeholder="Ex.: Loja Virtual — pedidos"
            />
            @if (form.controls.name.touched && form.controls.name.invalid) {
              <span class="error">Informe um nome com ao menos 2 caracteres.</span>
            }
          </div>
          <div class="field">
            <label for="ep-desc">Descrição</label>
            <input
              id="ep-desc"
              class="input"
              formControlName="description"
              placeholder="Opcional"
            />
          </div>
          <div class="field">
            <label for="ep-path">Caminho do ID do evento no payload</label>
            <input id="ep-path" class="input mono" formControlName="event_id_path" />
            <span class="help">
              Usado para idempotência quando o header <code>X-ConnectHub-Event-Id</code> não é
              enviado. Ex.: <code>id</code>, <code>data.order.id</code>. Sem ID, usa-se o hash
              SHA-256 do corpo.
            </span>
          </div>
        </form>
        <div footer>
          <button class="btn" (click)="showCreate.set(false)">Cancelar</button>
          <button class="btn primary" type="submit" form="create-endpoint" [disabled]="saving()">
            Criar endpoint
          </button>
        </div>
      </ch-modal>
    }

    @if (created(); as c) {
      <ch-modal title="Endpoint criado" (closed)="finishCreate(c)">
        <div class="alert warning">
          <b>Guarde o segredo de assinatura agora.</b> Por segurança ele é armazenado cifrado e só
          pode ser revelado novamente por um ADMIN (ação auditada).
        </div>
        <div class="field mt-2">
          <label>URL de ingestão</label>
          <div class="copy-field">
            <code>{{ c.ingest_url }}</code
            ><ch-copy [value]="c.ingest_url" />
          </div>
        </div>
        <div class="field">
          <label>Segredo de assinatura (HMAC-SHA256)</label>
          <div class="copy-field">
            <code>{{ c.signing_secret }}</code
            ><ch-copy [value]="c.signing_secret" />
          </div>
        </div>
        <div footer>
          <button class="btn primary" (click)="finishCreate(c)">Configurar destinos</button>
        </div>
      </ch-modal>
    }
  `,
})
export class EndpointsComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  readonly endpoints = signal<Endpoint[]>([]);
  readonly loading = signal(true);
  readonly showCreate = signal(false);
  readonly saving = signal(false);
  readonly created = signal<EndpointWithSecret | null>(null);

  readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    description: [''],
    event_id_path: [
      'id',
      [Validators.required, Validators.pattern(/^[A-Za-z0-9_\-.[\]$]{1,200}$/)],
    ],
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.api.endpoints(this.auth.orgId()).subscribe({
      next: (list) => {
        this.endpoints.set(list);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.toast.error(err);
      },
    });
  }

  openCreate(): void {
    this.form.reset({ name: '', description: '', event_id_path: 'id' });
    this.showCreate.set(true);
  }

  create(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.saving.set(true);
    const v = this.form.getRawValue();
    this.api
      .createEndpoint(this.auth.orgId(), { ...v, description: v.description || null })
      .subscribe({
        next: (ep) => {
          this.saving.set(false);
          this.showCreate.set(false);
          this.created.set(ep);
          this.load();
        },
        error: (err: unknown) => {
          this.saving.set(false);
          this.toast.error(err);
        },
      });
  }

  finishCreate(ep: Endpoint): void {
    this.created.set(null);
    void this.router.navigate(['/endpoints', ep.id]);
  }

  open(ep: Endpoint): void {
    void this.router.navigate(['/endpoints', ep.id]);
  }
}
