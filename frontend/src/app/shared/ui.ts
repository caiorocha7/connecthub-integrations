import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';

import { formatBytes, prettyJson, relativeTime, statusLabel, statusTone } from '../core/format';
import { IconComponent } from './icon.component';

@Component({
  selector: 'ch-status',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="badge {{ tone() }}" [class.pulse]="live()">{{ label() }}</span>`,
})
export class StatusBadgeComponent {
  readonly status = input.required<string>();
  readonly tone = computed(() => statusTone(this.status()));
  readonly label = computed(() => statusLabel(this.status()));
  readonly live = computed(() => ['PROCESSING', 'RETRYING', 'IN_PROGRESS'].includes(this.status()));
}

@Component({
  selector: 'ch-http-code',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (code() === null || code() === undefined) {
      <span class="faint">—</span>
    } @else {
      <span class="badge plain mono {{ tone() }}">{{ code() }}</span>
    }
  `,
})
export class HttpCodeComponent {
  readonly code = input<number | null | undefined>(null);
  readonly tone = computed(() => {
    const c = this.code() ?? 0;
    if (c >= 200 && c < 300) return 'success';
    if (c === 429 || (c >= 500 && c < 600)) return 'warning';
    return 'danger';
  });
}

@Component({
  selector: 'ch-kpi',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="kpi card">
      <div class="kpi-top">
        <span class="kpi-label">{{ label() }}</span>
        <span class="kpi-icon {{ tone() }}"><ch-icon [name]="icon()" [size]="16" /></span>
      </div>
      <div class="kpi-value">{{ value() }}</div>
      @if (hint()) {
        <div class="kpi-hint">{{ hint() }}</div>
      }
    </div>
  `,
  styles: [
    `
      .kpi {
        padding: 16px 18px;
      }
      .kpi-top {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .kpi-label {
        color: var(--ch-text-2);
        font-size: 12.5px;
        font-weight: 550;
      }
      .kpi-icon {
        width: 30px;
        height: 30px;
        border-radius: 8px;
        display: grid;
        place-items: center;
        background: var(--ch-primary-50);
        color: var(--ch-primary);
      }
      .kpi-icon.success {
        background: var(--ch-success-50);
        color: var(--ch-success);
      }
      .kpi-icon.danger {
        background: var(--ch-danger-50);
        color: var(--ch-danger);
      }
      .kpi-icon.warning {
        background: var(--ch-warning-50);
        color: var(--ch-warning);
      }
      .kpi-icon.accent {
        background: var(--ch-accent-50);
        color: #0f8f82;
      }
      .kpi-value {
        font-size: 28px;
        font-weight: 700;
        margin-top: 8px;
        letter-spacing: -0.02em;
      }
      .kpi-hint {
        color: var(--ch-text-3);
        font-size: 12px;
        margin-top: 2px;
      }
    `,
  ],
})
export class KpiCardComponent {
  readonly label = input.required<string>();
  readonly value = input.required<string | number>();
  readonly icon = input('zap');
  readonly tone = input<'' | 'success' | 'danger' | 'warning' | 'accent'>('');
  readonly hint = input<string | null>(null);
}

@Component({
  selector: 'ch-empty',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="empty">
      <div class="empty-icon"><ch-icon [name]="icon()" [size]="22" /></div>
      <h3>{{ title() }}</h3>
      @if (message()) {
        <p>{{ message() }}</p>
      }
      <ng-content />
    </div>
  `,
  styles: [
    `
      .empty {
        text-align: center;
        padding: 48px 20px;
        color: var(--ch-text-2);
      }
      .empty-icon {
        width: 48px;
        height: 48px;
        margin: 0 auto 12px;
        border-radius: 14px;
        display: grid;
        place-items: center;
        background: var(--ch-primary-50);
        color: var(--ch-primary);
      }
      h3 {
        color: var(--ch-text);
        margin-bottom: 4px;
      }
      p {
        margin: 0 auto 16px;
        max-width: 420px;
      }
    `,
  ],
})
export class EmptyStateComponent {
  readonly icon = input('zap');
  readonly title = input.required<string>();
  readonly message = input<string | null>(null);
}

@Component({
  selector: 'ch-loading',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="loading">
      @for (i of rowsArray(); track i) {
        <div class="skeleton" [style.width.%]="90 - (i % 3) * 15"></div>
      }
    </div>
  `,
  styles: ['.loading{padding:20px;display:flex;flex-direction:column;gap:14px}'],
})
export class LoadingComponent {
  readonly rows = input(4);
  readonly rowsArray = computed(() => Array.from({ length: this.rows() }, (_, i) => i));
}

@Component({
  selector: 'ch-pagination',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    @if (total() > 0) {
      <div class="pager">
        <span class="faint small"> {{ from() }}–{{ to() }} de {{ total() }} </span>
        <div class="row">
          <button
            class="btn sm icon"
            [disabled]="page() <= 1"
            (click)="pageChange.emit(page() - 1)"
            aria-label="Anterior"
          >
            <ch-icon name="chevron-left" [size]="16" />
          </button>
          <span class="small">Página {{ page() }} de {{ pages() || 1 }}</span>
          <button
            class="btn sm icon"
            [disabled]="page() >= pages()"
            (click)="pageChange.emit(page() + 1)"
            aria-label="Próxima"
          >
            <ch-icon name="chevron-right" [size]="16" />
          </button>
        </div>
      </div>
    }
  `,
  styles: [
    '.pager{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-top:1px solid var(--ch-border);gap:12px;flex-wrap:wrap}',
  ],
})
export class PaginationComponent {
  readonly page = input.required<number>();
  readonly pages = input.required<number>();
  readonly total = input.required<number>();
  readonly pageSize = input.required<number>();
  readonly pageChange = output<number>();
  readonly from = computed(() => (this.page() - 1) * this.pageSize() + 1);
  readonly to = computed(() => Math.min(this.page() * this.pageSize(), this.total()));
}

@Component({
  selector: 'ch-modal',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <div class="backdrop" (click)="closed.emit()"></div>
    <div class="modal card" role="dialog" aria-modal="true" [style.max-width.px]="width()">
      <div class="modal-header">
        <h2>{{ title() }}</h2>
        <button class="btn ghost sm icon" (click)="closed.emit()" aria-label="Fechar">
          <ch-icon name="x" />
        </button>
      </div>
      <div class="modal-body"><ng-content /></div>
      <div class="modal-footer"><ng-content select="[footer]" /></div>
    </div>
  `,
  styles: [
    `
      :host {
        position: fixed;
        inset: 0;
        z-index: 100;
        display: grid;
        place-items: center;
        padding: 16px;
      }
      .backdrop {
        position: absolute;
        inset: 0;
        background: rgba(11, 14, 29, 0.55);
        backdrop-filter: blur(2px);
      }
      .modal {
        position: relative;
        width: 100%;
        max-height: calc(100vh - 32px);
        display: flex;
        flex-direction: column;
        box-shadow: var(--ch-shadow-lg);
        animation: pop 0.15s ease-out;
      }
      .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        border-bottom: 1px solid var(--ch-border);
      }
      .modal-body {
        padding: 20px;
        overflow: auto;
      }
      .modal-footer {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
        padding: 14px 20px;
        border-top: 1px solid var(--ch-border);
      }
      .modal-footer:empty {
        display: none;
      }
      @keyframes pop {
        from {
          transform: translateY(8px);
          opacity: 0;
        }
      }
    `,
  ],
})
export class ModalComponent {
  readonly title = input.required<string>();
  readonly width = input(560);
  readonly closed = output<void>();
}

@Component({
  selector: 'ch-copy',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [IconComponent],
  template: `
    <button
      class="btn sm"
      type="button"
      (click)="copy()"
      [attr.aria-label]="'Copiar ' + (label() || '')"
    >
      <ch-icon [name]="copied() ? 'check' : 'copy'" [size]="14" />
      {{ copied() ? 'Copiado' : label() || 'Copiar' }}
    </button>
  `,
})
export class CopyButtonComponent {
  readonly value = input.required<string>();
  readonly label = input<string | null>(null);
  readonly copied = signal(false);

  copy(): void {
    void navigator.clipboard?.writeText(this.value()).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 1500);
    });
  }
}

@Component({
  selector: 'ch-json',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CopyButtonComponent],
  template: `
    <div class="json-wrap">
      <div class="json-tools"><ch-copy [value]="text()" label="JSON" /></div>
      <pre class="code-block">{{ text() }}</pre>
    </div>
  `,
  styles: ['.json-wrap{position:relative}.json-tools{position:absolute;top:8px;right:8px}'],
})
export class JsonViewerComponent {
  readonly value = input<unknown>(null);
  readonly text = computed(() => prettyJson(this.value()));
}

@Component({
  selector: 'ch-time',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span [title]="value() ?? ''" class="nowrap">{{ rel() }}</span>`,
})
export class RelativeTimeComponent {
  readonly value = input<string | null | undefined>(null);
  readonly rel = computed(() => relativeTime(this.value()));
}

@Component({
  selector: 'ch-bytes',
  template: `{{ text() }}`,
})
export class BytesComponent {
  readonly value = input.required<number>();
  readonly text = computed(() => formatBytes(this.value()));
}

export const SHARED_UI = [
  StatusBadgeComponent,
  HttpCodeComponent,
  KpiCardComponent,
  EmptyStateComponent,
  LoadingComponent,
  PaginationComponent,
  ModalComponent,
  CopyButtonComponent,
  JsonViewerComponent,
  RelativeTimeComponent,
  BytesComponent,
  IconComponent,
] as const;
