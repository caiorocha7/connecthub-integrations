import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { DeliveryStatus, DeliverySummary, Page } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import { ConfirmService } from '../../shared/confirm';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-failures',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Falhas e reprocessamento</h1>
          <p class="subtitle">
            Entregas que esgotaram as tentativas ou aguardam retentativa. Reprocessos são
            autorizados e auditados.
          </p>
        </div>
        <div class="actions">
          @if (tab() === 'FAILED' && selected().size > 0) {
            <button class="btn primary" (click)="replaySelected()" [disabled]="busy()">
              <ch-icon name="replay" [size]="15" /> Reprocessar {{ selected().size }} selecionada(s)
            </button>
          }
          <button class="btn icon" (click)="load()" aria-label="Atualizar">
            <ch-icon name="refresh" [size]="16" />
          </button>
        </div>
      </div>

      <div class="card">
        <div class="tabs">
          <button [class.active]="tab() === 'FAILED'" (click)="setTab('FAILED')">
            Falharam ({{ counts().FAILED }})
          </button>
          <button [class.active]="tab() === 'RETRYING'" (click)="setTab('RETRYING')">
            Em retentativa ({{ counts().RETRYING }})
          </button>
        </div>
        @if (!page()) {
          <ch-loading [rows]="5" />
        } @else if (page()!.items.length === 0) {
          <ch-empty
            icon="check"
            [title]="tab() === 'FAILED' ? 'Nenhuma entrega falhou' : 'Nada aguardando retentativa'"
            message="Use o simulador para provocar falhas e ver a recuperação em ação."
          />
        } @else {
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  @if (tab() === 'FAILED') {
                    <th style="width:36px">
                      <input
                        type="checkbox"
                        [checked]="allSelected()"
                        (change)="toggleAll()"
                        aria-label="Selecionar todas"
                      />
                    </th>
                  }
                  <th>Evento</th>
                  <th>Destino</th>
                  <th>Tentativas</th>
                  <th>HTTP</th>
                  <th>Erro</th>
                  <th>{{ tab() === 'FAILED' ? 'Falhou' : 'Próxima tentativa' }}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (d of page()!.items; track d.id) {
                  <tr>
                    @if (tab() === 'FAILED') {
                      <td>
                        <input
                          type="checkbox"
                          [checked]="selected().has(d.id)"
                          (change)="toggle(d.id)"
                          [attr.aria-label]="'Selecionar ' + d.external_event_id"
                        />
                      </td>
                    }
                    <td>
                      <code class="truncate" style="max-width:180px">{{
                        d.external_event_id
                      }}</code>
                    </td>
                    <td>
                      <b>{{ d.destination_name }}</b>
                    </td>
                    <td>{{ d.attempt_count }}/{{ d.max_attempts }}</td>
                    <td><ch-http-code [code]="d.last_status_code" /></td>
                    <td class="small">
                      <span class="truncate" style="color:var(--ch-danger);max-width:260px">{{
                        d.last_error || '—'
                      }}</span>
                    </td>
                    <td class="faint">
                      <ch-time [value]="tab() === 'FAILED' ? d.failed_at : d.next_attempt_at" />
                    </td>
                    <td class="actions-cell">
                      <button class="btn sm ghost" (click)="open(d)">Detalhes</button>
                      @if (d.status === 'FAILED') {
                        <button class="btn sm" (click)="replayOne(d)" [disabled]="busy()">
                          <ch-icon name="replay" [size]="14" /> Reprocessar
                        </button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
          <ch-pagination
            [page]="page()!.page"
            [pages]="page()!.pages"
            [total]="page()!.total"
            [pageSize]="page()!.page_size"
            (pageChange)="goTo($event)"
          />
        }
      </div>
    </div>
  `,
})
export class FailuresComponent {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly confirm = inject(ConfirmService);
  private readonly router = inject(Router);

  readonly tab = signal<DeliveryStatus>('FAILED');
  readonly page = signal<Page<DeliverySummary> | null>(null);
  readonly counts = signal<Record<'FAILED' | 'RETRYING', number>>({ FAILED: 0, RETRYING: 0 });
  readonly selected = signal<Set<string>>(new Set());
  readonly busy = signal(false);
  private currentPage = 1;

  readonly allSelected = computed(() => {
    const items = this.page()?.items ?? [];
    return items.length > 0 && items.every((i) => this.selected().has(i.id));
  });

  constructor() {
    this.load();
    startPolling(() => this.load(true), 5000);
  }

  setTab(tab: DeliveryStatus): void {
    this.tab.set(tab);
    this.currentPage = 1;
    this.selected.set(new Set());
    this.page.set(null);
    this.load();
  }

  goTo(p: number): void {
    this.currentPage = p;
    this.load();
  }

  load(silent = false): void {
    const org = this.auth.orgId();
    forkJoin({
      page: this.api.deliveries(org, { status: this.tab(), page: this.currentPage, page_size: 20 }),
      failed: this.api.deliveries(org, { status: 'FAILED', page_size: 1 }),
      retrying: this.api.deliveries(org, { status: 'RETRYING', page_size: 1 }),
    }).subscribe({
      next: ({ page, failed, retrying }) => {
        this.page.set(page);
        this.counts.set({ FAILED: failed.total, RETRYING: retrying.total });
        const visible = new Set(page.items.map((i) => i.id));
        this.selected.update((s) => new Set([...s].filter((id) => visible.has(id))));
      },
      error: (err: unknown) => {
        if (!silent) this.toast.error(err);
      },
    });
  }

  toggle(id: string): void {
    this.selected.update((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  toggleAll(): void {
    const items = this.page()?.items ?? [];
    this.selected.set(this.allSelected() ? new Set() : new Set(items.map((i) => i.id)));
  }

  open(d: DeliverySummary): void {
    void this.router.navigate(['/deliveries', d.id]);
  }

  replayOne(d: DeliverySummary): void {
    this.run([d.id]);
  }

  async replaySelected(): Promise<void> {
    const ids = [...this.selected()];
    const ok = await this.confirm.ask({
      title: 'Reprocessar entregas',
      message: `${ids.length} entrega(s) receberão um novo ciclo de tentativas. A ação será auditada.`,
      confirmLabel: 'Reprocessar',
    });
    if (ok) this.run(ids);
  }

  private run(ids: string[]): void {
    const org = this.auth.orgId();
    this.busy.set(true);
    forkJoin(ids.map((id) => this.api.replayDelivery(org, id))).subscribe({
      next: () => {
        this.busy.set(false);
        this.selected.set(new Set());
        this.toast.success(`${ids.length} entrega(s) reenfileirada(s).`);
        this.load();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.toast.error(err);
        this.load();
      },
    });
  }
}
