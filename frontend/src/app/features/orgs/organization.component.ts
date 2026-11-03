import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { Member, Role } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-organization',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Organização</h1>
          <p class="subtitle">
            Todos os recursos são isolados por organização. ADMIN configura; OPERATOR acompanha e
            reprocessa.
          </p>
        </div>
        <div class="actions">
          <button class="btn" (click)="showNewOrg.set(true)">
            <ch-icon name="plus" [size]="16" /> Nova organização
          </button>
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-header">
            <h2>Membros</h2>
            <span class="hint">{{ members().length }} pessoa(s)</span>
          </div>
          <div class="card-body flush">
            @if (loading()) {
              <ch-loading />
            } @else {
              <div class="table-wrap">
                <table class="table">
                  <thead>
                    <tr>
                      <th>Nome</th>
                      <th>E-mail</th>
                      <th>Papel</th>
                      <th>Desde</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (m of members(); track m.id) {
                      <tr>
                        <td>
                          <b>{{ m.full_name }}</b>
                          @if (m.user_id === auth.user()?.id) {
                            <span class="badge plain info">você</span>
                          }
                        </td>
                        <td>{{ m.email }}</td>
                        <td>
                          @if (auth.isAdmin()) {
                            <select
                              class="input sm"
                              style="width:auto"
                              [value]="m.role"
                              (change)="changeRole(m, $event)"
                            >
                              <option value="ADMIN">ADMIN</option>
                              <option value="OPERATOR">OPERATOR</option>
                            </select>
                          } @else {
                            <span class="badge plain" [class.primary]="m.role === 'ADMIN'">{{
                              m.role
                            }}</span>
                          }
                        </td>
                        <td class="faint">{{ m.created_at | date: 'dd/MM/yyyy' }}</td>
                        <td class="actions-cell">
                          @if (auth.isAdmin()) {
                            <button
                              class="btn sm ghost icon danger"
                              (click)="remove(m)"
                              aria-label="Remover membro"
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
              <form class="add-member" [formGroup]="memberForm" (ngSubmit)="addMember()">
                <input
                  class="input sm"
                  type="email"
                  formControlName="email"
                  placeholder="email@empresa.com (conta já cadastrada)"
                  aria-label="E-mail"
                />
                <select
                  class="input sm"
                  formControlName="role"
                  style="width:auto"
                  aria-label="Papel"
                >
                  <option value="OPERATOR">OPERATOR</option>
                  <option value="ADMIN">ADMIN</option>
                </select>
                <button class="btn sm primary" type="submit" [disabled]="memberForm.invalid">
                  <ch-icon name="plus" [size]="14" /> Adicionar
                </button>
              </form>
            }
          </div>
        </div>

        <div class="stack">
          <div class="card">
            <div class="card-header"><h2>Dados da organização</h2></div>
            <form class="card-body" [formGroup]="orgForm" (ngSubmit)="rename()">
              <div class="field">
                <label for="o-name">Nome</label>
                <input
                  id="o-name"
                  class="input"
                  formControlName="name"
                  [readonly]="!auth.isAdmin()"
                />
              </div>
              <dl class="kv small">
                <dt>Identificador</dt>
                <dd class="mono">{{ auth.currentMembership()?.organization_slug }}</dd>
                <dt>ID</dt>
                <dd class="mono">{{ auth.currentOrgId() }}</dd>
                <dt>Seu papel</dt>
                <dd>{{ auth.currentMembership()?.role }}</dd>
              </dl>
              @if (auth.isAdmin()) {
                <button
                  class="btn primary mt-2"
                  type="submit"
                  [disabled]="orgForm.invalid || orgForm.pristine"
                >
                  Salvar
                </button>
              }
            </form>
          </div>
          <div class="card">
            <div class="card-header"><h2>Permissões</h2></div>
            <div class="card-body small">
              <table class="table">
                <thead>
                  <tr>
                    <th>Ação</th>
                    <th>ADMIN</th>
                    <th>OPERATOR</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>Ver dashboard, eventos e entregas</td>
                    <td>✓</td>
                    <td>✓</td>
                  </tr>
                  <tr>
                    <td>Reprocessar entregas</td>
                    <td>✓</td>
                    <td>✓</td>
                  </tr>
                  <tr>
                    <td>Configurar endpoints, destinos e regras</td>
                    <td>✓</td>
                    <td>—</td>
                  </tr>
                  <tr>
                    <td>Revelar / rotacionar segredos</td>
                    <td>✓</td>
                    <td>—</td>
                  </tr>
                  <tr>
                    <td>Gerenciar membros e ver auditoria</td>
                    <td>✓</td>
                    <td>—</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>

    @if (showNewOrg()) {
      <ch-modal title="Nova organização" [width]="440" (closed)="showNewOrg.set(false)">
        <form [formGroup]="newOrgForm" (ngSubmit)="createOrg()" id="new-org" novalidate>
          <div class="field">
            <label for="n-org">Nome</label>
            <input id="n-org" class="input" formControlName="name" placeholder="Ex.: Filial Sul" />
          </div>
          <p class="small muted" style="margin:0">
            Você será ADMIN. Os dados ficam totalmente isolados das demais organizações.
          </p>
        </form>
        <div footer>
          <button class="btn" (click)="showNewOrg.set(false)">Cancelar</button>
          <button class="btn primary" type="submit" form="new-org" [disabled]="newOrgForm.invalid">
            Criar
          </button>
        </div>
      </ch-modal>
    }
  `,
  styles: [
    '.add-member{display:flex;gap:8px;padding:14px 20px;border-top:1px solid var(--ch-border);flex-wrap:wrap}.add-member input{flex:1;min-width:200px}',
  ],
})
export class OrganizationComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly router = inject(Router);
  private readonly fb = inject(FormBuilder);

  readonly members = signal<Member[]>([]);
  readonly loading = signal(true);
  readonly showNewOrg = signal(false);

  readonly orgForm = this.fb.nonNullable.group({
    name: [
      this.auth.currentMembership()?.organization_name ?? '',
      [Validators.required, Validators.minLength(2)],
    ],
  });
  readonly memberForm = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    role: ['OPERATOR' as Role],
  });
  readonly newOrgForm = this.fb.nonNullable.group({
    name: ['', [Validators.required, Validators.minLength(2)]],
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.api.members(this.auth.orgId()).subscribe({
      next: (m) => {
        this.members.set(m);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.toast.error(err);
      },
    });
  }

  rename(): void {
    this.api.updateOrg(this.auth.orgId(), this.orgForm.getRawValue().name).subscribe({
      next: () => {
        this.toast.success('Organização atualizada.');
        this.orgForm.markAsPristine();
        this.auth.loadMe().subscribe();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  addMember(): void {
    const v = this.memberForm.getRawValue();
    this.api.addMember(this.auth.orgId(), v.email, v.role).subscribe({
      next: () => {
        this.toast.success('Membro adicionado.');
        this.memberForm.reset({ email: '', role: 'OPERATOR' });
        this.load();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  changeRole(m: Member, event: Event): void {
    const role = (event.target as HTMLSelectElement).value as Role;
    this.api.updateMember(this.auth.orgId(), m.id, role).subscribe({
      next: () => {
        this.toast.success(`Papel de ${m.full_name} alterado para ${role}.`);
        this.load();
        if (m.user_id === this.auth.user()?.id) this.auth.loadMe().subscribe();
      },
      error: (err: unknown) => {
        this.toast.error(err);
        this.load();
      },
    });
  }

  async remove(m: Member): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Remover membro',
      message: `Remover ${m.full_name} (${m.email}) desta organização?`,
      confirmLabel: 'Remover',
      danger: true,
    });
    if (!ok) return;
    this.api.removeMember(this.auth.orgId(), m.id).subscribe({
      next: () => {
        this.toast.success('Membro removido.');
        if (m.user_id === this.auth.user()?.id) {
          this.auth.loadMe().subscribe(() => void this.router.navigate(['/dashboard']));
        } else {
          this.load();
        }
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }

  createOrg(): void {
    this.api.createOrg(this.newOrgForm.getRawValue().name).subscribe({
      next: (org) => {
        this.showNewOrg.set(false);
        this.newOrgForm.reset({ name: '' });
        this.toast.success(`Organização "${org.name}" criada.`);
        this.auth.loadMe().subscribe(() => {
          this.auth.selectOrg(org.id);
          void this.router.navigate(['/dashboard']);
        });
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
