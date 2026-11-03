import { DeliveryStatus, EventStatus } from './models';

export type BadgeTone = 'success' | 'danger' | 'warning' | 'info' | 'primary' | 'accent' | '';

const STATUS_TONE: Record<string, BadgeTone> = {
  SUCCEEDED: 'success',
  SUCCESS: 'success',
  FAILED: 'danger',
  PERMANENT_ERROR: 'danger',
  RETRYING: 'warning',
  RETRYABLE_ERROR: 'warning',
  PROCESSING: 'info',
  IN_PROGRESS: 'info',
  PENDING: '',
  RECEIVED: 'primary',
  IGNORED: '',
};

const STATUS_LABEL: Record<string, string> = {
  SUCCEEDED: 'Sucesso',
  SUCCESS: 'Sucesso',
  FAILED: 'Falhou',
  PERMANENT_ERROR: 'Erro permanente',
  RETRYING: 'Retentando',
  RETRYABLE_ERROR: 'Erro temporário',
  PROCESSING: 'Processando',
  IN_PROGRESS: 'Em andamento',
  PENDING: 'Pendente',
  RECEIVED: 'Recebido',
  IGNORED: 'Sem rota',
};

export function statusTone(status: string): BadgeTone {
  return STATUS_TONE[status] ?? '';
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status] ?? status;
}

export const EVENT_STATUSES: EventStatus[] = [
  'RECEIVED',
  'PROCESSING',
  'RETRYING',
  'SUCCEEDED',
  'FAILED',
  'IGNORED',
];
export const DELIVERY_STATUSES: DeliveryStatus[] = [
  'PENDING',
  'PROCESSING',
  'RETRYING',
  'SUCCEEDED',
  'FAILED',
];

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—';
  const diff = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diff);
  const fmt = (v: number, unit: string) => (diff < 0 ? `há ${v} ${unit}` : `em ${v} ${unit}`);
  if (abs < 5) return 'agora';
  if (abs < 60) return fmt(abs, 's');
  if (abs < 3600) return fmt(Math.round(abs / 60), 'min');
  if (abs < 86400) return fmt(Math.round(abs / 3600), 'h');
  return fmt(Math.round(abs / 86400), 'd');
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function prettyJson(value: unknown): string {
  if (value === null || value === undefined) return '—';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** Converts a value from <input type="datetime-local"> to an ISO string (or null). */
export function localInputToIso(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
