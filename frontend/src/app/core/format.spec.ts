import { HttpErrorResponse } from '@angular/common/http';
import { describe, expect, it } from 'vitest';

import {
  formatBytes,
  localInputToIso,
  prettyJson,
  relativeTime,
  statusLabel,
  statusTone,
} from './format';
import { apiErrorMessage } from './toast.service';

describe('format helpers', () => {
  it('maps statuses to tones and labels', () => {
    expect(statusTone('SUCCEEDED')).toBe('success');
    expect(statusTone('FAILED')).toBe('danger');
    expect(statusTone('RETRYING')).toBe('warning');
    expect(statusLabel('RETRYING')).toBe('Retentando');
    expect(statusLabel('UNKNOWN')).toBe('UNKNOWN');
  });

  it('formats relative time in pt-BR', () => {
    const now = Date.parse('2026-01-01T12:00:00Z');
    expect(relativeTime('2026-01-01T11:59:58Z', now)).toBe('agora');
    expect(relativeTime('2026-01-01T11:58:00Z', now)).toBe('há 2 min');
    expect(relativeTime('2026-01-01T15:00:00Z', now)).toBe('em 3 h');
    expect(relativeTime(null, now)).toBe('—');
  });

  it('formats bytes and json', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2.0 KB');
    expect(prettyJson({ a: 1 })).toBe('{\n  "a": 1\n}');
    expect(prettyJson(null)).toBe('—');
  });

  it('converts datetime-local values to ISO', () => {
    expect(localInputToIso('')).toBeNull();
    expect(localInputToIso('invalid')).toBeNull();
    expect(localInputToIso('2026-01-01T10:00')).toMatch(/^2026-01-01T\d{2}:00:00\.000Z$/);
  });
});

describe('apiErrorMessage', () => {
  it('reads FastAPI string details', () => {
    const err = new HttpErrorResponse({ status: 409, error: { detail: 'e-mail já cadastrado' } });
    expect(apiErrorMessage(err)).toBe('e-mail já cadastrado');
  });

  it('reads field validation errors', () => {
    const err = new HttpErrorResponse({
      status: 422,
      error: { detail: 'dados inválidos', errors: [{ field: 'password', message: 'muito curta' }] },
    });
    expect(apiErrorMessage(err)).toBe('password: muito curta');
  });

  it('reads structured rule errors and network failures', () => {
    const rule = new HttpErrorResponse({
      status: 422,
      error: { detail: { message: 'regra inválida', errors: ['x'] } },
    });
    expect(apiErrorMessage(rule)).toBe('regra inválida · x');
    expect(apiErrorMessage(new HttpErrorResponse({ status: 0 }))).toContain(
      'Não foi possível conectar',
    );
    expect(apiErrorMessage(new Error('boom'), 'fallback')).toBe('fallback');
  });
});
