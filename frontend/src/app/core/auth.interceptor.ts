import { HttpErrorResponse, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, switchMap, throwError } from 'rxjs';

import { AuthService } from './auth.service';

const PUBLIC_AUTH_PATHS = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'];

function withToken(req: HttpRequest<unknown>, token: string | null): HttpRequest<unknown> {
  return token ? req.clone({ setHeaders: { Authorization: `Bearer ${token}` } }) : req;
}

/** Adds the bearer token and transparently refreshes it once on 401. */
export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const router = inject(Router);
  const isApi = req.url.startsWith('/api/');
  if (!isApi || PUBLIC_AUTH_PATHS.some((p) => req.url.includes(p))) {
    return next(req);
  }
  return next(withToken(req, auth.accessToken())).pipe(
    catchError((error: unknown) => {
      if (error instanceof HttpErrorResponse && error.status === 401 && auth.refreshToken()) {
        return auth.refreshAccessToken().pipe(
          switchMap((token) => next(withToken(req, token))),
          catchError((refreshError: unknown) => {
            auth.clearSession();
            void router.navigate(['/login'], { queryParams: { expired: 1 } });
            return throwError(() => refreshError);
          }),
        );
      }
      return throwError(() => error);
    }),
  );
};
