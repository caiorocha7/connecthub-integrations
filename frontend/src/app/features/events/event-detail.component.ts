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
import { Router, RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { AuthService } from '../../core/auth.service';
import { EventDetail } from '../../core/models';
import { startPolling } from '../../core/polling';
import { ToastService } from '../../core/toast.service';
import { SHARED_UI } from '../../shared/ui';

@Component({
  selector: 'ch-event-detail',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, DatePipe, ...SHARED_UI],
  template: `
    <div class="page">
      @if (event(); as e) {
        <div class="breadcrumb">
          <a routerLink="/events">Eventos</a> / <span class="mono">{{ e.external_event_id }}</span>
        </div>
        <div class="page-header">
          <div>
            <h1 class="row">
              Evento <code style="font-size:18px">{{ e.external_event_id }}</code>
              <ch-status [status]="e.status" />
            </h1>
            <p class="subtitle">
              Recebido em {{ e.received_at | date: 'dd/MM/yyyy HH:mm:ss' }} pelo endpoint
              <b>{{ e.endpoint_name }}</b>
            </p>
          </div>
          <div class="actions">
            @if (hasFailures()) {
              <button class="btn primary" (click)="replay(e)" [disabled]="busy()">
                <ch-icon name="replay" [size]="15" /> Reprocessar falhas
              </button>
            }
            <button class="btn icon" (click)="load()" aria-label="Atualizar">
              <ch-icon name="refresh" [size]="16" />
            </button>
          </div>
        </div>

        <div class="grid grid-2">
          <div class="stack">
            <div class="card">
              <div class="card-header">
                <h2>Entregas lógicas</h2>
                <span class="hint">uma por destino — nunca duplicadas</span>
              </div>
              <div class="card-body flush">
                @if (e.deliveries.length === 0) {
                  <ch-empty
                    icon="destination"
                    title="Nenhuma entrega"
                    message="Não havia rota ativa para este endpoint quando o evento chegou."
                  />
                } @else {
                  <div class="table-wrap">
                    <table class="table">
                      <thead>
                        <tr>
                          <th>Destino</th>
                          <th>Status</th>
                          <th>Tentativas</th>
                          <th>Último HTTP</th>
                          <th>Próxima tentativa</th>
                          <th></th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (d of e.deliveries; track d.id) {
                          <tr class="clickable" [routerLink]="['/deliveries', d.id]">
                            <td>
                              <b>{{ d.destination_name }}</b>
                              @if (d.last_error && d.status !== 'SUCCEEDED') {
                                <div class="small" style="color:var(--ch-danger)">
                                  {{ d.last_error }}
                                </div>
                              }
                            </td>
                            <td><ch-status [status]="d.status" /></td>
                            <td>
                              {{ d.attempt_count }}/{{ d.max_attempts }}
                              @if (d.replay_count) {
                                <span class="badge plain info">{{ d.replay_count }} replay</span>
                              }
                            </td>
                            <td><ch-http-code [code]="d.last_status_code" /></td>
                            <td>
                              @if (d.status === 'RETRYING') {
                                <ch-time [value]="d.next_attempt_at" />
                              } @else {
                                <span class="faint">—</span>
                              }
                            </td>
                            <td class="actions-cell">
                              <ch-icon name="chevron-right" [size]="16" />
                            </td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                }
              </div>
            </div>
            <div class="card">
              <div class="card-header">
                <h2>Payload original</h2>
                <span class="hint">campos sensíveis mascarados</span>
              </div>
              <div class="card-body"><ch-json [value]="e.payload" /></div>
            </div>
          </div>
          <div class="stack">
            <div class="card">
              <div class="card-header"><h2>Metadados</h2></div>
              <div class="card-body">
                <dl class="kv small">
                  <dt>ID interno</dt>
                  <dd class="mono">{{ e.id }}</dd>
                  <dt>Chave de idempotência</dt>
                  <dd class="mono">organização + endpoint + {{ e.external_event_id }}</dd>
                  <dt>Origem do ID</dt>
                  <dd>{{ e.event_id_source }}</dd>
                  <dt>Tamanho</dt>
                  <dd><ch-bytes [value]="e.payload_size" /></dd>
                  <dt>IP de origem</dt>
                  <dd>{{ e.source_ip || '—' }}</dd>
                  <dt>Duplicados bloqueados</dt>
                  <dd>
                    {{ e.duplicate_count }}
                    @if (e.last_duplicate_at) {
                      <span class="faint">(último <ch-time [value]="e.last_duplicate_at" />)</span>
                    }
                  </dd>
                </dl>
              </div>
            </div>
            <div class="card">
              <div class="card-header"><h2>Headers recebidos</h2></div>
              <div class="card-body"><ch-json [value]="e.headers" /></div>
            </div>
          </div>
        </div>
      } @else {
        <div class="card"><ch-loading [rows]="6" /></div>
      }
    </div>
  `,
})
export class EventDetailComponent implements OnInit {
  readonly id = input.required<string>();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);
  private readonly router = inject(Router);

  readonly event = signal<EventDetail | null>(null);
  readonly busy = signal(false);
  readonly hasFailures = computed(
    () => this.event()?.deliveries.some((d) => d.status === 'FAILED') ?? false,
  );

  constructor() {
    startPolling(() => {
      const s = this.event()?.status;
      if (s && !['SUCCEEDED', 'FAILED', 'IGNORED'].includes(s)) this.load();
    }, 3000);
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.event(this.auth.orgId(), this.id()).subscribe({
      next: (e) => this.event.set(e),
      error: (err: unknown) => {
        this.toast.error(err);
        void this.router.navigate(['/events']);
      },
    });
  }

  replay(e: EventDetail): void {
    this.busy.set(true);
    this.api.replayEvent(this.auth.orgId(), e.id).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.toast.success(`${r.replayed} entrega(s) reenfileirada(s).`);
        this.load();
      },
      error: (err: unknown) => {
        this.busy.set(false);
        this.toast.error(err);
      },
    });
  }
}
