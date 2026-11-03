import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, finalize, firstValueFrom, map, of, shareReplay, tap } from 'rxjs';

import { ApiService } from './api.service';
import { Me, MembershipSummary, TokenResponse } from './models';

const ACCESS_KEY = 'ch.access';
const REFRESH_KEY = 'ch.refresh';
const ORG_KEY = 'ch.org';

function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function storageSet(key: string, value: string | null): void {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* storage unavailable: keep session in memory only */
  }
}

/**
 * Session state. Access tokens are short-lived JWTs; refresh tokens are opaque, rotated on each use
 * and revoked on logout (server side).
 */
@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);

  readonly accessToken = signal<string | null>(storageGet(ACCESS_KEY));
  readonly refreshToken = signal<string | null>(storageGet(REFRESH_KEY));
  readonly user = signal<Me | null>(null);
  readonly currentOrgId = signal<string | null>(storageGet(ORG_KEY));

  readonly isAuthenticated = computed(() => !!this.refreshToken() && !!this.user());
  readonly memberships = computed<MembershipSummary[]>(() => this.user()?.memberships ?? []);
  readonly currentMembership = computed(
    () => this.memberships().find((m) => m.organization_id === this.currentOrgId()) ?? null,
  );
  readonly isAdmin = computed(() => this.currentMembership()?.role === 'ADMIN');

  private refreshInFlight: Observable<string> | null = null;

  /** Current organization id; the shell only renders once this is set. */
  orgId(): string {
    const id = this.currentOrgId();
    if (!id) throw new Error('no organization selected');
    return id;
  }

  async bootstrap(): Promise<void> {
    if (!this.refreshToken()) return;
    try {
      await firstValueFrom(this.loadMe());
    } catch {
      this.clearSession();
    }
  }

  loadMe(): Observable<Me> {
    return this.api.me().pipe(
      tap((me) => {
        this.user.set(me);
        const current = this.currentOrgId();
        if (!current || !me.memberships.some((m) => m.organization_id === current)) {
          this.selectOrg(me.memberships[0]?.organization_id ?? null);
        }
      }),
    );
  }

  login(email: string, password: string): Observable<Me> {
    return new Observable<Me>((subscriber) => {
      const sub = this.api.login(email, password).subscribe({
        next: (tokens) => {
          this.storeTokens(tokens);
          this.loadMe().subscribe(subscriber);
        },
        error: (err) => subscriber.error(err),
      });
      return () => sub.unsubscribe();
    });
  }

  register(body: {
    email: string;
    password: string;
    full_name: string;
    organization_name?: string | null;
  }): Observable<Me> {
    return new Observable<Me>((subscriber) => {
      const sub = this.api.register(body).subscribe({
        next: (tokens) => {
          this.storeTokens(tokens);
          this.loadMe().subscribe(subscriber);
        },
        error: (err) => subscriber.error(err),
      });
      return () => sub.unsubscribe();
    });
  }

  /** Refresh the access token once even if many requests fail with 401 at the same time. */
  refreshAccessToken(): Observable<string> {
    const token = this.refreshToken();
    if (!token) return new Observable((s) => s.error(new Error('no refresh token')));
    if (!this.refreshInFlight) {
      this.refreshInFlight = this.api.refresh(token).pipe(
        tap((tokens) => this.storeTokens(tokens)),
        map((tokens) => tokens.access_token),
        finalize(() => (this.refreshInFlight = null)),
        shareReplay(1),
      );
    }
    return this.refreshInFlight;
  }

  logout(): void {
    const token = this.refreshToken();
    const done = () => {
      this.clearSession();
      void this.router.navigate(['/login']);
    };
    if (!token) return done();
    this.api
      .logout(token)
      .pipe(catchError(() => of(undefined)))
      .subscribe(() => done());
  }

  selectOrg(orgId: string | null): void {
    this.currentOrgId.set(orgId);
    storageSet(ORG_KEY, orgId);
  }

  clearSession(): void {
    this.accessToken.set(null);
    this.refreshToken.set(null);
    this.user.set(null);
    storageSet(ACCESS_KEY, null);
    storageSet(REFRESH_KEY, null);
  }

  private storeTokens(tokens: TokenResponse): void {
    this.accessToken.set(tokens.access_token);
    this.refreshToken.set(tokens.refresh_token);
    storageSet(ACCESS_KEY, tokens.access_token);
    storageSet(REFRESH_KEY, tokens.refresh_token);
  }
}
