import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { TransformRule } from '../../core/models';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-transforms',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Regras de transformação</h1>
          <p class="subtitle">
            Mapeamentos declarativos de JSON — renomear, selecionar caminhos, valores padrão e
            conversões. Nenhum código é executado.
          </p>
        </div>
        @if (auth.isAdmin()) {
          <div class="actions">
            <a class="btn primary" routerLink="/transforms/new"
              ><ch-icon name="plus" [size]="16" /> Nova regra</a
            >
          </div>
        }
      </div>

      @if (loading()) {
        <div class="card"><ch-loading /></div>
      } @else if (rules().length === 0) {
        <div class="card">
          <ch-empty
            icon="transform"
            title="Nenhuma regra"
            message="Crie uma regra e associe-a a uma rota endpoint → destino."
          >
            @if (auth.isAdmin()) {
              <a class="btn primary" routerLink="/transforms/new"
                ><ch-icon name="plus" [size]="16" /> Criar regra</a
              >
            }
          </ch-empty>
        </div>
      } @else {
        <div class="grid rules">
          @for (r of rules(); track r.id) {
            <div class="card rule">
              <div class="card-body">
                <div class="row" style="justify-content:space-between">
                  <h2>
                    <a [routerLink]="['/transforms', r.id]">{{ r.name }}</a>
                  </h2>
                  <span class="badge plain primary">{{ r.mappings.length }} campo(s)</span>
                </div>
                <p class="muted small">{{ r.description || 'Sem descrição' }}</p>
                <div class="chips">
                  @for (m of r.mappings.slice(0, 5); track $index) {
                    <span class="chip mono"
                      >{{ m.source || '“' + m.value + '”' }} → {{ m.target }}</span
                    >
                  }
                  @if (r.mappings.length > 5) {
                    <span class="chip">+{{ r.mappings.length - 5 }}</span>
                  }
                </div>
              </div>
              <div class="rule-footer">
                <span class="faint small">Atualizada <ch-time [value]="r.updated_at" /></span>
                <div class="row" style="gap:4px">
                  <a class="btn sm" [routerLink]="['/transforms', r.id]">{{
                    auth.isAdmin() ? 'Editar' : 'Ver'
                  }}</a>
                  @if (auth.isAdmin()) {
                    <button
                      class="btn sm ghost icon danger"
                      (click)="remove(r)"
                      aria-label="Excluir"
                    >
                      <ch-icon name="trash" [size]="14" />
                    </button>
                  }
                </div>
              </div>
            </div>
          }
        </div>
      }
    </div>
  `,
  styles: [
    `
      .rules {
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      }
      .rule {
        display: flex;
        flex-direction: column;
      }
      .rule .card-body {
        flex: 1;
      }
      .chips {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
      }
      .chip {
        background: var(--ch-neutral-50);
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 11.5px;
        color: var(--ch-text-2);
      }
      .rule-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 20px;
        border-top: 1px solid var(--ch-border);
      }
    `,
  ],
})
export class TransformsComponent {
  readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);

  readonly rules = signal<TransformRule[]>([]);
  readonly loading = signal(true);

  constructor() {
    this.load();
  }

  load(): void {
    this.api.rules(this.auth.orgId()).subscribe({
      next: (r) => {
        this.rules.set(r);
        this.loading.set(false);
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.toast.error(err);
      },
    });
  }

  async remove(r: TransformRule): Promise<void> {
    const ok = await this.confirm.ask({
      title: 'Excluir regra',
      message: `Excluir "${r.name}"? Rotas que a utilizam passarão a enviar o payload original.`,
      confirmLabel: 'Excluir',
      danger: true,
    });
    if (!ok) return;
    this.api.deleteRule(this.auth.orgId(), r.id).subscribe({
      next: () => {
        this.toast.success('Regra excluída.');
        this.load();
      },
      error: (err: unknown) => this.toast.error(err),
    });
  }
}
