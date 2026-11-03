import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { EVENT_STATUSES, localInputToIso, statusLabel } from '../../core/format';
import { Destination, Endpoint, EventSummary, Page } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-events',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      <div class="page-header">
        <div>
          <h1>Eventos recebidos</h1>
          <p class="subtitle">
            Cada webhook aceito é persistido antes da confirmação. Duplicados são contabilizados,
            não reprocessados.
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
        <form class="filters" [formGroup]="filters" (ngSubmit)="applyFilters()">
          <div class="field">
            <label for="f-search">ID do evento</label>
            <input
              id="f-search"
              class="input sm mono"
              formControlName="search"
              placeholder="ord_1001"
            />
          </div>
          <div class="field">
            <label for="f-status">Status</label>
            <select id="f-status" class="input sm" formControlName="status">
              <option value="">Todos</option>
              @for (s of statuses; track s) {
                <option [value]="s">{{ label(s) }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="f-ep">Endpoint</label>
            <select id="f-ep" class="input sm" formControlName="endpoint_id">
              <option value="">Todos</option>
              @for (e of endpoints(); track e.id) {
                <option [value]="e.id">{{ e.name }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="f-dest">Destino</label>
            <select id="f-dest" class="input sm" formControlName="destination_id">
              <option value="">Todos</option>
              @for (d of destinations(); track d.id) {
                <option [value]="d.id">{{ d.name }}</option>
              }
            </select>
          </div>
          <div class="field">
            <label for="f-from">De</label>
            <input id="f-from" class="input sm" type="datetime-local" formControlName="date_from" />
          </div>
          <div class="field">
            <label for="f-to">Até</label>
            <input id="f-to" class="input sm" type="datetime-local" formControlName="date_to" />
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
              icon="events"
              title="Nenhum evento encontrado"
              message="Envie um webhook assinado para um endpoint ativo ou ajuste os filtros."
            />
          } @else {
            <div class="table-wrap">
              <table class="table">
                <thead>
                  <tr>
                    <th>ID externo</th>
                    <th>Endpoint</th>
                    <th>Status</th>
                    <th>Entregas</th>
                    <th>Duplicados</th>
                    <th>Tamanho</th>
                    <th>Recebido em</th>
                  </tr>
                </thead>
                <tbody>
                  @for (e of p.items; track e.id) {
                    <tr class="clickable" (click)="open(e)">
                      <td>
                        <code class="truncate">{{ e.external_event_id }}</code>
                        <div class="faint small">
                          via
                          {{
                            e.event_id_source === 'header'
                              ? 'header'
                              : e.event_id_source === 'payload'
                                ? 'payload'
                                : 'hash do corpo'
                          }}
                        </div>
                      </td>
                      <td>{{ e.endpoint_name }}</td>
                      <td><ch-status [status]="e.status" /></td>
                      <td>{{ e.delivery_count }}</td>
                      <td>
                        @if (e.duplicate_count > 0) {
                          <span class="badge plain warning"
                            >{{ e.duplicate_count }}× bloqueado</span
                          >
                        } @else {
                          <span class="faint">—</span>
                        }
                      </td>
                      <td class="faint"><ch-bytes [value]="e.payload_size" /></td>
                      <td class="nowrap">{{ e.received_at | date: 'dd/MM/yy HH:mm:ss' }}</td>
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
export class EventsComponent {
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);
  private readonly fb = inject(FormBuilder);

  readonly statuses = EVENT_STATUSES;
  readonly label = statusLabel;
  readonly page = signal<Page<EventSummary> | null>(null);
  readonly loading = signal(true);
  readonly live = signal(true);
  readonly endpoints = signal<Endpoint[]>([]);
  readonly destinations = signal<Destination[]>([]);
  private currentPage = 1;

  readonly filters = this.fb.nonNullable.group({
    search: [''],
    status: [''],
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

  applyFilters(): void {
    this.currentPage = 1;
    this.load();
  }

  clear(): void {
    this.filters.reset({
      search: '',
      status: '',
      endpoint_id: '',
      destination_id: '',
      date_from: '',
      date_to: '',
    });
    this.applyFilters();
  }

  goTo(page: number): void {
    this.currentPage = page;
    this.load();
  }

  load(silent = false): void {
    if (!silent) this.loading.set(true);
    const f = this.filters.getRawValue();
    this.api
      .events(this.auth.orgId(), {
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

  open(e: EventSummary): void {
    void this.router.navigate(['/events', e.id]);
  }
}
