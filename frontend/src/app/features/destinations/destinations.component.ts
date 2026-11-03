import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormArray, FormBuilder, FormGroup, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Destination, HttpMethod } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

const URL_PATTERN = /^https?:\/\/[^\s/$.?#].[^\s]*$/i;

@Component({
  selector: 'ch-destinations',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Destinos HTTP</h1>
          <p class="subtitle">
            Sistemas que recebem os eventos processados, com timeout e política de retentativas
            próprios.
          </p>
        </div>
        @if (auth.isAdmin()) {
          <div class="actions">
            <button class="btn primary" (click)="openForm(null)">
              <ch-icon name="plus" [size]="16" /> Novo destino
            </button>
          </div>
        }
      </div>

      <div class="card">
        @if (loading()) {
          <ch-loading />
        } @else if (items().length === 0) {
          <ch-empty
            icon="destination"
            title="Nenhum destino cadastrado"
            message="Dica: para a demonstração, use o simulador local em http://simulator:8131/hooks/erp."
          >
            @if (auth.isAdmin()) {
              <button class="btn primary" (click)="openForm(null)">
                <ch-icon name="plus" [size]="16" /> Criar destino
              </button>
            }
          </ch-empty>
        } @else {
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>URL</th>
                  <th>Método</th>
                  <th>Timeout</th>
                  <th>Tentativas</th>
                  <th>Assinatura</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (d of items(); track d.id) {
                  <tr>
                    <td>
                      <b>{{ d.name }}</b>
                      @if (d.description) {
                        <div class="faint small truncate">{{ d.description }}</div>
                      }
                    </td>
                    <td>
                      <code class="truncate">{{ d.url }}</code>
                    </td>
                    <td>
                      <span class="badge plain">{{ d.method }}</span>
                    </td>
                    <td>{{ d.timeout_seconds }}s</td>
                    <td>{{ d.max_attempts }}</td>
                    <td>
                      @if (d.has_signing_secret) {
                        <span class="badge plain accent">HMAC</span>
                      } @else {
                        <span class="faint small">—</span>
                      }
                    </td>
                    <td>
                      <span class="switch" [title]="d.is_active ? 'Ativo' : 'Inativo'">
                        <input
                          type="checkbox"
                          [checked]="d.is_active"
                          [disabled]="!auth.isAdmin()"
                          (change)="toggle(d)"
                        /><span></span>
                      </span>
                    </td>
                    <td class="actions-cell">
                      <a
                        class="btn sm ghost"
                        [routerLink]="['/deliveries']"
                        [queryParams]="{ destination_id: d.id }"
                        >Entregas</a
                      >
                      @if (auth.isAdmin()) {
                        <button class="btn sm ghost icon" (click)="openForm(d)" aria-label="Editar">
                          <ch-icon name="edit" [size]="14" />
                        </button>
                        <button
                          class="btn sm ghost icon danger"
                          (click)="remove(d)"
                          aria-label="Excluir"
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
      </div>
    </div>

    @if (formOpen()) {
      <ch-modal
        [title]="editing() ? 'Editar destino' : 'Novo destino'"
        [width]="640"
        (closed)="formOpen.set(false)"
      >
        <form [formGroup]="form" (ngSubmit)="save()" id="dest-form" novalidate>
          <div class="form-grid">
            <div class="field">
              <label for="d-name">Nome</label>
              <input
                id="d-name"
                class="input"
                formControlName="name"
                placeholder="Ex.: ERP financeiro"
              />
              @if (form.controls.name.touched && form.controls.name.invalid) {
                <span class="error">Informe um nome.</span>
              }
            </div>
            <div class="field">
              <label for="d-method">Método</label>
              <select id="d-method" class="input" formControlName="method">
                @for (m of methods; track m) {
                  <option [value]="m">{{ m }}</option>
                }
              </select>
            </div>
            <div class="field full">
              <label for="d-url">URL</label>
              <input
                id="d-url"
                class="input mono"
                formControlName="url"
                placeholder="https://api.exemplo.com/webhooks"
              />
              <span class="help"
                >Endereços privados, loopback e metadados de nuvem são bloqueados (proteção SSRF).
                Redirecionamentos não são seguidos.</span
              >
              @if (form.controls.url.touched && form.controls.url.invalid) {
                <span class="error">Informe uma URL http(s) válida.</span>
              }
            </div>
            <div class="field">
              <label for="d-timeout">Timeout (segundos)</label>
              <input
                id="d-timeout"
                class="input"
                type="number"
                min="1"
                max="60"
                formControlName="timeout_seconds"
              />
            </div>
            <div class="field">
              <label for="d-attempts">Máximo de tentativas</label>
              <input
                id="d-attempts"
                class="input"
                type="number"
                min="1"
                max="20"
                formControlName="max_attempts"
              />
            </div>
            <div class="field full">
              <label for="d-desc">Descrição</label>
              <input id="d-desc" class="input" formControlName="description" />
            </div>
          </div>

          <div class="field">
            <label>Headers adicionais</label>
            <div formArrayName="headers" class="stack" style="gap:8px">
              @for (h of headers.controls; track $index; let i = $index) {
                <div class="row" [formGroupName]="i" style="flex-wrap:nowrap">
                  <input
                    class="input sm mono"
                    formControlName="name"
                    placeholder="X-Api-Key"
                    aria-label="Nome do header"
                  />
                  <input
                    class="input sm mono"
                    formControlName="value"
                    placeholder="valor"
                    aria-label="Valor do header"
                  />
                  <button
                    type="button"
                    class="btn sm ghost icon danger"
                    (click)="headers.removeAt(i)"
                    aria-label="Remover header"
                  >
                    <ch-icon name="x" [size]="14" />
                  </button>
                </div>
              }
            </div>
            <div>
              <button type="button" class="btn sm" (click)="addHeader()">
                <ch-icon name="plus" [size]="14" /> Header
              </button>
            </div>
            <span class="help"
              >Headers de controle (Host, Content-Type, Content-Length, X-ConnectHub-*) são
              gerenciados pela plataforma.</span
            >
          </div>

          <div class="field">
            <label for="d-secret">Segredo para assinar a entrega (opcional)</label>
            <input
              id="d-secret"
              class="input mono"
              type="password"
              formControlName="signing_secret"
              [placeholder]="
                editing()?.has_signing_secret
                  ? '•••••• (mantido — preencha para substituir)'
                  : 'mín. 16 caracteres'
              "
            />
            <span class="help"
              >Se definido, cada entrega inclui <code>X-ConnectHub-Signature</code> para o destino
              validar a origem.</span
            >
          </div>
          <label class="checkbox"
            ><input type="checkbox" formControlName="is_active" /> Destino ativo</label
          >
        </form>
        <div footer>
          <button class="btn" (click)="formOpen.set(false)">Cancelar</button>
          <button class="btn primary" type="submit" form="dest-form" [disabled]="saving()">
            Salvar
          </button>
        </div>
      </ch-modal>
    }
  `,
})
export class DestinationsComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly fb = inject(FormBuilder);

  readonly methods: HttpMethod[] = ['POST', 'PUT', 'PATCH'];
  readonly items = signal<Destination[]>([]);
  readonly loading = signal(true);
  readonly formOpen = signal(false);
  readonly saving = signal(false);
  readonly editing = signal<Destination | null>(null);

  readonly form = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2), Validators.maxLength(120)]],
    description: [''],
    url: ['', [Validators.required, Validators.pattern(URL_PATTERN)]],
    method: ['POST' as HttpMethod],
    timeout_seconds: [10, [Validators.required, Validators.min(1), Validators.max(60)]],
    max_attempts: [5, [Validators.required, Validators.min(1), Validators.max(20)]],
    signing_secret: ['', [Validators.minLength(16)]],
    is_active: [true],
    headers: this.fb.array<FormGroup>([]),
  });

  get headers(): FormArray<FormGroup> {
    return this.form.controls.headers;
  }

  constructor() {
    this.load();
  }

  load(): void {
    this.api.destinations(this.auth.orgId()).subscribe({
      next: (list) => {
        this.items.set(list);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.toast.error(err);
      },
    });
  }

  addHeader(name = '', value = ''): void {
    this.headers.push(
      this.fb.nonNullable.group({
        name: [name, [Validators.required, Validators.pattern(/^[A-Za-z0-9][A-Za-z0-9-]{0,63}$/)]],
        value: [value, [Validators.required, Validators.maxLength(1024)]],
      }),
    );
  }

  openForm(dest: Destination | null): void {
    this.editing.set(dest);
    this.headers.clear();
    this.form.reset({
      name: dest?.name ?? '',
      description: dest?.description ?? '',
      url: dest?.url ?? 'http://simulator:8131/hooks/erp',
      method: dest?.method ?? 'POST',
      timeout_seconds: dest?.timeout_seconds ?? 10,
      max_attempts: dest?.max_attempts ?? 5,
      signing_secret: '',
      is_active: dest?.is_active ?? true,
    });
    Object.entries(dest?.headers ?? {}).forEach(([k, v]) => this.addHeader(k, v));
    this.formOpen.set(true);
  }

  save(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    const v = this.form.getRawValue();
    const headers: Record<string, string> = {};
    for (const h of v.headers as { name: string; value: string }[]) headers[h.name] = h.value;
    const body: Record<string, unknown> = {
      name: v.name,
      description: v.description || null,
      url: v.url,
      method: v.method,
      timeout_seconds: v.timeout_seconds,
      max_attempts: v.max_attempts,
      is_active: v.is_active,
      headers,
    };
    if (v.signing_secret) body['signing_secret'] = v.signing_secret;
    const current = this.editing();
    const req = current
      ? this.api.updateDestination(this.auth.orgId(), current.id, body)
      : this.api.createDestination(this.auth.orgId(), body);
    this.saving.set(true);
    req.subscribe({
      next: () => {
        this.saving.set(false);
        this.formOpen.set(false);
        this.toast.success(current ? 'Destino atualizado.' : 'Destino criado.');
        this.load();
      },
      error: (err: unknown) => {
        this.saving.set(false);
        this.toast.error(err);
      },
    });
  }

  toggle(d: Destination): void {
    this.api.updateDestination(this.auth.orgId(), d.id, { is_active: !d.is_active }).subscribe({
      next: () => this.load(),
      error: (err: unknown) => this.toast.error(err),
    });
  }

  async remove(d: Destination): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Excluir destino',
      message: `Excluir "${d.name}"? Destinos com entregas no histórico não podem ser excluídos — desative-os.`,
      confirmLabel: 'Excluir',
      danger: true,
    });
    if (!ok) return;
    this.api.deleteDestination(this.auth.orgId(), d.id).subscribe({
      next: () => {
        this.toast.success('Destino excluído.');
        this.load();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
