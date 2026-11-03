import { ChangeDetectionStrategy, Component, Injectable, inject, signal } from '@angular/core';

import { ModalComponent } from './ui';

interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  danger: boolean;
  resolve: (ok: boolean) => void;
}

/** Promise-based confirmation dialog rendered by the application shell. */
@Injectable({ providedIn: 'root' })
export class ConfirmService {
  readonly current = signal<ConfirmRequest | null>(null);

  ask(options: {
    title: string;
    message: string;
    confirmLabel?: string;
    danger?: boolean;
  }): Promise<boolean> {
    return new Promise((resolve) => {
      this.current.set({
        title: options.title,
        message: options.message,
        confirmLabel: options.confirmLabel ?? 'Confirmar',
        danger: options.danger ?? false,
        resolve,
      });
    });
  }

  answer(ok: boolean): void {
    const req = this.current();
    this.current.set(null);
    req?.resolve(ok);
  }
}

@Component({
  selector: 'ch-confirm-host',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ModalComponent],
  template: `
    @if (confirm.current(); as req) {
      <ch-modal [title]="req.title" [width]="440" (closed)="confirm.answer(false)">
        <p class="muted" style="margin:0">{{ req.message }}</p>
        <div footer>
          <button class="btn" (click)="confirm.answer(false)">Cancelar</button>
          <button
            class="btn"
            [class.danger-solid]="req.danger"
            [class.primary]="!req.danger"
            (click)="confirm.answer(true)"
          >
            {{ req.confirmLabel }}
          </button>
        </div>
      </ch-modal>
    }
  `,
})
export class ConfirmHostComponent {
  readonly confirm = inject(ConfirmService);
}
