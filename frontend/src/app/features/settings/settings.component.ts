import { DatePipe, JsonPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import {
  AbstractControl,
  FormBuilder,
  ReactiveFormsModule,
  ValidationErrors,
  Validators,
} from '@angular/forms';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { AuditLog, Page } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

function matchPasswords(group: AbstractControl): ValidationErrors | null {
  const a = group.get('new_password')?.value;
  const b = group.get('confirm')?.value;
  return a && b && a !== b ? { mismatch: true } : null;
}

@Component({
  selector: 'ch-settings',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DatePipe, JsonPipe, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Configurações</h1>
          <p class="subtitle">Perfil, segurança da conta e trilha de auditoria da organização.</p>
        </div>
      </div>

      <div class="grid grid-half">
        <div class="card">
          <div class="card-header"><h2>Perfil</h2></div>
          <form class="card-body" [formGroup]="profile" (ngSubmit)="saveProfile()">
            <div class="field">
              <label for="p-name">Nome</label>
              <input id="p-name" class="input" formControlName="full_name" />
            </div>
            <div class="field">
              <label>E-mail</label>
              <input class="input" [value]="auth.user()?.email" readonly />
            </div>
            <button
              class="btn primary"
              type="submit"
              [disabled]="profile.invalid || profile.pristine"
            >
              Salvar perfil
            </button>
          </form>
        </div>
        <div class="card">
          <div class="card-header">
            <h2>Alterar senha</h2>
            <span class="hint">encerra as demais sessões</span>
          </div>
          <form class="card-body" [formGroup]="password" (ngSubmit)="changePassword()">
            <div class="field">
              <label for="p-cur">Senha atual</label>
              <input
                id="p-cur"
                class="input"
                type="password"
                formControlName="current_password"
                autocomplete="current-password"
              />
            </div>
            <div class="form-grid">
              <div class="field">
                <label for="p-new">Nova senha</label>
                <input
                  id="p-new"
                  class="input"
                  type="password"
                  formControlName="new_password"
                  autocomplete="new-password"
                />
              </div>
              <div class="field">
                <label for="p-conf">Confirmar</label>
                <input
                  id="p-conf"
                  class="input"
                  type="password"
                  formControlName="confirm"
                  autocomplete="new-password"
                />
              </div>
            </div>
            @if (password.errors?.['mismatch']) {
              <div class="error small" style="margin-bottom:12px">As senhas não conferem.</div>
            }
            @if (password.controls.new_password.touched && password.controls.new_password.invalid) {
              <div class="error small" style="margin-bottom:12px">
                Mínimo de 8 caracteres, com letras e números.
              </div>
            }
            <button class="btn primary" type="submit" [disabled]="password.invalid">
              Alterar senha
            </button>
          </form>
        </div>
      </div>

      <div class="card mt-2">
        <div class="card-header"><h2>Integração e API</h2></div>
        <div class="card-body">
          <dl class="kv small">
            <dt>Documentação OpenAPI</dt>
            <dd>
              <a href="/docs" target="_blank" rel="noopener">/docs</a> (Swagger UI) ·
              <a href="/openapi.json" target="_blank" rel="noopener">/openapi.json</a>
            </dd>
            <dt>Assinatura de entrada</dt>
            <dd>
              <code>X-ConnectHub-Signature: v1=HMAC_SHA256(segredo, timestamp + "." + corpo)</code>
            </dd>
            <dt>Janela anti-replay</dt>
            <dd>5 minutos (configurável via <code>SIGNATURE_TOLERANCE_SECONDS</code>)</dd>
            <dt>Idempotência</dt>
            <dd>
              organização + endpoint + ID do evento (header <code>X-ConnectHub-Event-Id</code>,
              caminho no payload ou hash do corpo)
            </dd>
            <dt>Sessão</dt>
            <dd>
              Token de acesso de curta duração com refresh rotativo; o logout revoga o refresh token
              no servidor.
            </dd>
          </dl>
        </div>
      </div>

      @if (auth.isAdmin()) {
        <div class="card mt-2">
          <div class="card-header">
            <h2>Auditoria</h2>
            <span class="hint">ações administrativas e reprocessamentos</span>
          </div>
          <div class="card-body flush">
            @if (audit(); as a) {
              @if (a.items.length === 0) {
                <ch-empty icon="shield" title="Sem registros" />
              } @else {
                <div class="table-wrap">
                  <table class="table">
                    <thead>
                      <tr>
                        <th>Quando</th>
                        <th>Quem</th>
                        <th>Ação</th>
                        <th>Recurso</th>
                        <th>Detalhes</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (log of a.items; track log.id) {
                        <tr>
                          <td class="nowrap">{{ log.created_at | date: 'dd/MM/yy HH:mm:ss' }}</td>
                          <td>{{ log.actor_email || 'sistema' }}</td>
                          <td>
                            <code>{{ log.action }}</code>
                          </td>
                          <td class="small">
                            {{ log.resource_type }}
                            <span class="faint mono">{{ log.resource_id?.slice(0, 8) }}</span>
                          </td>
                          <td class="small">
                            <code class="truncate" style="max-width:320px">{{
                              log.details | json
                            }}</code>
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
                <ch-pagination
                  [page]="a.page"
                  [pages]="a.pages"
                  [total]="a.total"
                  [pageSize]="a.page_size"
                  (pageChange)="loadAudit($event)"
                />
              }
            } @else {
              <ch-loading />
            }
          </div>
        </div>
      }
    </div>
  `,
})
export class SettingsComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly fb = inject(FormBuilder);

  readonly audit = signal<Page<AuditLog> | null>(null);

  readonly profile = this.fb.nonNullable.group({
    full_name: [this.auth.user()?.full_name ?? '', [Validators.required, Validators.minLength(2)]],
  });
  readonly password = this.fb.nonNullable.group(
    {
      current_password: ['', Validators.required],
      new_password: [
        '',
        [Validators.required, Validators.pattern(/^(?=.*[A-Za-z])(?=.*\d).{8,}$/)],
      ],
      confirm: ['', Validators.required],
    },
    { validators: matchPasswords },
  );

  constructor() {
    if (this.auth.isAdmin()) this.loadAudit(1);
  }

  loadAudit(page: number): void {
    this.api.auditLogs(this.auth.orgId(), { page, page_size: 15 }).subscribe({
      next: (a) => this.audit.set(a),
      error: (err: unknown) => this.toast.error(err),
    });
  }

  saveProfile(): void {
    this.api.updateMe(this.profile.getRawValue().full_name).subscribe({
      next: (me) => {
        this.auth.user.set(me);
        this.profile.markAsPristine();
        this.toast.success('Perfil atualizado.');
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  changePassword(): void {
    const v = this.password.getRawValue();
    this.api.changePassword(v.current_password, v.new_password).subscribe({
      next: () => {
        this.toast.success('Senha alterada. Faça login novamente.');
        this.auth.clearSession();
        this.auth.logout();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
