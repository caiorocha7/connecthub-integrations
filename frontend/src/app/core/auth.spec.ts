import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { authInterceptor } from './auth.interceptor';
import { AuthService } from './auth.service';

const ME = {
  id: 'u1',
  email: 'ana@example.com',
  full_name: 'Ana',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  memberships: [
    { organization_id: 'org-a', organization_name: 'A', organization_slug: 'a', role: 'ADMIN' },
    { organization_id: 'org-b', organization_name: 'B', organization_slug: 'b', role: 'OPERATOR' },
  ],
};

describe('AuthService + authInterceptor', () => {
  let http: HttpClient;
  let backend: HttpTestingController;
  let auth: AuthService;

  beforeEach(() => {
    localStorage.clear();
    TestBed.configureTestingModule({
      providers: [
        provideRouter([{ path: 'login', children: [] }]),
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
      ],
    });
    http = TestBed.inject(HttpClient);
    backend = TestBed.inject(HttpTestingController);
    auth = TestBed.inject(AuthService);
  });

  afterEach(() => backend.verify());

  it('logs in, stores tokens and selects the first organization', () => {
    let done = false;
    auth.login('ana@example.com', 'Senha123').subscribe(() => (done = true));
    backend.expectOne('/api/v1/auth/login').flush({
      access_token: 'acc1',
      refresh_token: 'ref1',
      token_type: 'bearer',
      expires_in: 900,
    });
    const me = backend.expectOne('/api/v1/auth/me');
    expect(me.request.headers.get('Authorization')).toBe('Bearer acc1');
    me.flush(ME);
    expect(done).toBe(true);
    expect(auth.isAuthenticated()).toBe(true);
    expect(auth.currentOrgId()).toBe('org-a');
    expect(auth.isAdmin()).toBe(true);
    auth.selectOrg('org-b');
    expect(auth.isAdmin()).toBe(false);
    expect(localStorage.getItem('ch.refresh')).toBe('ref1');
  });

  it('refreshes the access token once on 401 and retries the request', () => {
    auth.accessToken.set('expired');
    auth.refreshToken.set('ref1');
    let body: unknown;
    http.get('/api/v1/orgs/org-a/events').subscribe((b) => (body = b));
    backend
      .expectOne('/api/v1/orgs/org-a/events')
      .flush({ detail: 'x' }, { status: 401, statusText: 'Unauthorized' });
    const refresh = backend.expectOne('/api/v1/auth/refresh');
    expect(refresh.request.body).toEqual({ refresh_token: 'ref1' });
    refresh.flush({
      access_token: 'acc2',
      refresh_token: 'ref2',
      token_type: 'bearer',
      expires_in: 900,
    });
    const retry = backend.expectOne('/api/v1/orgs/org-a/events');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer acc2');
    retry.flush({ items: [] });
    expect(body).toEqual({ items: [] });
    expect(auth.refreshToken()).toBe('ref2');
  });

  it('clears the session when refresh fails', () => {
    auth.accessToken.set('expired');
    auth.refreshToken.set('revoked');
    http.get('/api/v1/auth/me').subscribe({ error: () => undefined });
    backend.expectOne('/api/v1/auth/me').flush({}, { status: 401, statusText: 'Unauthorized' });
    backend
      .expectOne('/api/v1/auth/refresh')
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    expect(auth.refreshToken()).toBeNull();
    expect(auth.isAuthenticated()).toBe(false);
  });

  it('does not attach tokens to non-API or public auth requests', () => {
    auth.accessToken.set('acc');
    http.get('/sim-api/control').subscribe();
    http.post('/api/v1/auth/login', {}).subscribe();
    expect(backend.expectOne('/sim-api/control').request.headers.has('Authorization')).toBe(false);
    expect(backend.expectOne('/api/v1/auth/login').request.headers.has('Authorization')).toBe(
      false,
    );
  });
});
