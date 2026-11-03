import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';

export type ToastKind = 'success' | 'error' | 'info';

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

/** Extracts a human readable message from an API error (never exposes stack traces). */
export function apiErrorMessage(
  error: unknown,
  fallback = 'Não foi possível concluir a operação.',
): string {
  if (error instanceof HttpErrorResponse) {
    if (error.status === 0)
      return 'Não foi possível conectar à API. Verifique se os serviços estão no ar.';
    const body = error.error as {
      detail?: string | { message?: string; errors?: string[] };
      errors?: { field: string; message: string }[];
    } | null;
    if (body?.errors?.length) {
      return body.errors.map((e) => (e.field ? `${e.field}: ${e.message}` : e.message)).join(' · ');
    }
    if (typeof body?.detail === 'string') return body.detail;
    if (body?.detail && typeof body.detail === 'object') {
      const d = body.detail;
      return [d.message, ...(d.errors ?? [])].filter(Boolean).join(' · ');
    }
    if (error.status === 403) return 'Você não tem permissão para esta ação.';
    if (error.status === 404) return 'Recurso não encontrado.';
  }
  return fallback;
}

@Injectable({ providedIn: 'root' })
export class ToastService {
  readonly toasts = signal<Toast[]>([]);
  private seq = 0;

  show(kind: ToastKind, message: string, timeoutMs = 4500): void {
    const id = ++this.seq;
    this.toasts.update((list) => [...list, { id, kind, message }]);
    setTimeout(() => this.dismiss(id), timeoutMs);
  }

  success(message: string): void {
    this.show('success', message);
  }

  info(message: string): void {
    this.show('info', message);
  }

  error(error: unknown, fallback?: string): void {
    this.show('error', apiErrorMessage(error, fallback), 6500);
  }

  dismiss(id: number): void {
    this.toasts.update((list) => list.filter((t) => t.id !== id));
  }
}
