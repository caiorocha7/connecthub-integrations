import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';
import { apiErrorMessage } from '../../core/toast.service';
import { AUTH_STYLES } from './auth-layout';
import { AuthPitchComponent } from './auth-pitch.component';

@Component({
  selector: 'ch-login',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, AuthPitchComponent],
  template: `
    <ch-auth-pitch />
    <section class="panel">
      <form class="form-box" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <h2>Bem-vindo de volta</h2>
        <p class="lead">Entre para acompanhar suas integrações.</p>
        @if (expired) {
          <div class="alert info" style="margin-bottom:16px">
            Sua sessão expirou. Entre novamente.
          </div>
        }
        @if (error()) {
          <div class="alert danger" style="margin-bottom:16px" role="alert">{{ error() }}</div>
        }
        <div class="field">
          <label for="email">E-mail</label>
          <input
            id="email"
            class="input"
            type="email"
            formControlName="email"
            autocomplete="email"
          />
          @if (form.controls.email.touched && form.controls.email.invalid) {
            <span class="error">Informe um e-mail válido.</span>
          }
        </div>
        <div class="field">
          <label for="password">Senha</label>
          <input
            id="password"
            class="input"
            type="password"
            formControlName="password"
            autocomplete="current-password"
          />
          @if (form.controls.password.touched && form.controls.password.invalid) {
            <span class="error">Informe sua senha.</span>
          }
        </div>
        <button class="btn primary submit" type="submit" [disabled]="loading()">
          {{ loading() ? 'Entrando…' : 'Entrar' }}
        </button>
        <p class="switch-link">Ainda não tem conta? <a routerLink="/register">Criar conta</a></p>
        <div class="alert info demo">
          <b>Ambiente de demonstração:</b> após <code>docker compose up</code>, use o usuário criado
          pelo seed (padrão <code>demo&#64;example.com</code> / <code>Demo&#64;12345</code>,
          configurável no <code>.env</code>).
        </div>
      </form>
    </section>
  `,
  styles: [AUTH_STYLES],
})
export class LoginComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly expired = this.route.snapshot.queryParamMap.has('expired');

  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', Validators.required],
  });

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();
    this.auth.login(email, password).subscribe({
      next: () => {
        const next = this.route.snapshot.queryParamMap.get('next') || '/dashboard';
        void this.router.navigateByUrl(next.startsWith('/') ? next : '/dashboard');
      },
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível entrar.'));
      },
    });
  }
}
