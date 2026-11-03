import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';

import { ToastService } from './core/toast.service';
import { ConfirmHostComponent } from './shared/confirm';
import { IconComponent } from './shared/icon.component';

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, ConfirmHostComponent, IconComponent],
  template: `
    <router-outlet />
    <ch-confirm-host />
    <div class="toasts" aria-live="polite">
      @for (t of toast.toasts(); track t.id) {
        <div class="toast {{ t.kind }}" role="status">
          <ch-icon
            [name]="t.kind === 'success' ? 'check' : t.kind === 'error' ? 'failures' : 'zap'"
            [size]="16"
          />
          <span>{{ t.message }}</span>
          <button class="close" (click)="toast.dismiss(t.id)" aria-label="Fechar">×</button>
        </div>
      }
    </div>
  `,
  styles: [
    `
      .toasts {
        position: fixed;
        right: 20px;
        bottom: 20px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        z-index: 200;
        max-width: min(420px, calc(100vw - 40px));
      }
      .toast {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 12px 14px;
        border-radius: 10px;
        background: var(--ch-ink-900);
        color: #fff;
        box-shadow: var(--ch-shadow-lg);
        font-size: 13.5px;
        animation: slide 0.2s ease-out;
        border-left: 4px solid var(--ch-primary);
      }
      .toast.success {
        border-left-color: var(--ch-accent);
      }
      .toast.error {
        border-left-color: var(--ch-danger);
      }
      .toast span {
        flex: 1;
      }
      .close {
        background: none;
        border: none;
        color: var(--ch-ink-300);
        font-size: 18px;
        line-height: 1;
        cursor: pointer;
      }
      @keyframes slide {
        from {
          transform: translateY(10px);
          opacity: 0;
        }
      }
    `,
  ],
})
export class App {
  readonly toast = inject(ToastService);
}
