import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { DELIVERY_STATUSES, localInputToIso, statusLabel } from '../../core/format';
import { DeliverySummary, Destination, Endpoint, Page } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-deliveries',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Histórico de entregas</h1>
          <p class="subtitle">
            Cada entrega é a execução lógica de um evento para um destino, com suas tentativas HTTP.
          </p>
        </div>
        <div class="actions">
          <label class="row small" style="gap:8px">
            <span class="switch"
              ><input type="checkbox" [checked]="live()" (change)="live.set(!live())" /><span></span
            ></span>
            Ao vivo
          </label>
          <button class="btn icon" (click)="load()" aria-label="Atualizar">
            <ch-icon name="refresh" [size]="16" />
          </button>
        </div>
      </div>

      <div class="card">
        <form class="filters" [formGroup]="filters" (ngSubmit)="apply()">
          <div class="field">
            <label for="d-status">Status</label>
            <select id="d-status" class="input sm" formControlName="status">
              <option value="">Todos</option>
              @for (s of statuses; track s) {
                <option [value]="s">{{ label(s) }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="d-ep">Endpoint</label>
            <select id="d-ep" class="input sm" formControlName="endpoint_id">
              <option value="">Todos</option>
              @for (e of endpoints(); track e.id) {
                <option [value]="e.id">{{ e.name }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="d-dest">Destino</label>
            <select id="d-dest" class="input sm" formControlName="destination_id">
              <option value="">Todos</option>
              @for (d of destinations(); track d.id) {
                <option [value]="d.id">{{ d.name }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="d-from">De</label>
            <input id="d-from" class="input sm" type="datetime-local" formControlName="date_from" />
          </div>
          <div class="field">
            <label for="d-to">Até</label>
            <input id="d-to" class="input sm" type="datetime-local" formControlName="date_to" />
          </div>
          <button class="btn sm primary" type="submit">
            <ch-icon name="search" [size]="14" /> Filtrar
          </button>
          <button class="btn sm ghost" type="button" (click)="clear()">Limpar</button>
        </form>

        @if (loading() && !page()) {
          <ch-loading [rows]="6" />
        } @else if (page(); as p) {
          @if (p.items.length === 0) {
            <ch-empty
              icon="deliveries"
              title="Nenhuma entrega encontrada"
              message="Ajuste os filtros ou envie um evento para um endpoint com destino associado."
            />
          } @else {
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>Evento</th>
                    <th>Endpoint → Destino</th>
                    <th>Status</th>
                    <th>Tentativas</th>
                    <th>HTTP</th>
                    <th>Último erro</th>
                    <th>Atualizado</th>
                  </tr>
                </thead>
                <tbody>
                  @for (d of p.items; track d.id) {
                    <tr class="clickable" (click)="open(d)">
                      <td>
                        <code class="truncate" style="max-width:180px">{{
                          d.external_event_id
                        }}</code>
                      </td>
                      <td class="small">
                        {{ d.endpoint_name }} <span class="faint">→</span>
                        <b>{{ d.destination_name }}</b>
                      </td>
                      <td><ch-status [status]="d.status" /></td>
                      <td>{{ d.attempt_count }}/{{ d.max_attempts }}</td>
                      <td><ch-http-code [code]="d.last_status_code" /></td>
                      <td class="small">
                        @if (d.last_error && d.status !== 'SUCCEEDED') {
                          <span class="truncate" style="color:var(--ch-danger);max-width:240px">{{
                            d.last_error
                          }}</span>
                        } @else {
                          <span class="faint">—</span>
                        }
                      </td>
                      <td class="faint"><ch-time [value]="d.updated_at" /></td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
            <ch-pagination
              [page]="p.page"
              [pages]="p.pages"
              [total]="p.total"
              [pageSize]="p.page_size"
              (pageChange)="goTo($event)"
            />
          }
        }
      </div>
    </div>
  `,
})
export class DeliveriesComponent {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);

  readonly statuses = DELIVERY_STATUSES;
  readonly label = statusLabel;
  readonly page = signal<Page<DeliverySummary> | null>(null);
  readonly loading = signal(true);
  readonly live = signal(true);
  readonly endpoints = signal<Endpoint[]>([]);
  readonly destinations = signal<Destination[]>([]);
  private currentPage = 1;

  readonly filters = this.fb.nonNullable.group({
    status: [this.route.snapshot.queryParamMap.get('status') ?? ''],
    endpoint_id: [this.route.snapshot.queryParamMap.get('endpoint_id') ?? ''],
    destination_id: [this.route.snapshot.queryParamMap.get('destination_id') ?? ''],
    date_from: [''],
    date_to: [''],
  });

  constructor() {
    const org = this.auth.orgId();
    forkJoin({ e: this.api.endpoints(org), d: this.api.destinations(org) }).subscribe(
      ({ e, d }) => {
        this.endpoints.set(e);
        this.destinations.set(d);
      },
    );
    this.load();
    startPolling(() => {
      if (this.live()) this.load(true);
    }, 5000);
  }

  apply(): void {
    this.currentPage = 1;
    this.load();
  }

  clear(): void {
    this.filters.reset({
      status: '',
      endpoint_id: '',
      destination_id: '',
      date_from: '',
      date_to: '',
    });
    this.apply();
  }

  goTo(page: number): void {
    this.currentPage = page;
    this.load();
  }

  load(silent = false): void {
    if (!silent) this.loading.set(true);
    const f = this.filters.getRawValue();
    this.api
      .deliveries(this.auth.orgId(), {
        ...f,
        date_from: localInputToIso(f.date_from),
        date_to: localInputToIso(f.date_to),
        page: this.currentPage,
        page_size: 20,
      })
      .subscribe({
        next: (p) => {
          this.page.set(p);
          this.loading.set(false);
        },
        error: (err: unknown) => {
          this.loading.set(false);
          if (!silent) this.toast.error(err);
        },
      });
  }

  open(d: DeliverySummary): void {
    void this.router.navigate(['/deliveries', d.id]);
  }
}
