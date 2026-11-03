import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';
import { apiErrorMessage } from '../../core/toast.service';
import { AUTH_STYLES } from './auth-layout';
import { AuthPitchComponent } from './auth-pitch.component';

const PASSWORD_PATTERN = /^(?=.*[A-Za-z])(?=.*\d).{8,}$/;

@Component({
  selector: 'ch-register',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, AuthPitchComponent],
  template: `
    <ch-auth-pitch />
    <section class="panel">
      <form class="form-box" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <h2>Crie sua conta</h2>
        <p class="lead">Você será ADMIN da nova organização.</p>
        @if (error()) {
          <div class="alert danger" style="margin-bottom:16px" role="alert">{{ error() }}</div>
        }
        <div class="field">
          <label for="full_name">Nome completo</label>
          <input id="full_name" class="input" formControlName="full_name" autocomplete="name" />
          @if (form.controls.full_name.touched && form.controls.full_name.invalid) {
            <span class="error">Informe seu nome (mínimo 2 caracteres).</span>
          }
        </div>
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
            autocomplete="new-password"
          />
          <span class="help">Mínimo de 8 caracteres, com letras e números.</span>
          @if (form.controls.password.touched && form.controls.password.invalid) {
            <span class="error">Senha não atende aos requisitos.</span>
          }
        </div>
        <div class="field">
          <label for="org">Nome da organização</label>
          <input
            id="org"
            class="input"
            formControlName="organization_name"
            placeholder="Ex.: Loja Exemplo"
          />
          @if (form.controls.organization_name.touched && form.controls.organization_name.invalid) {
            <span class="error">Informe o nome da organização.</span>
          }
        </div>
        <button class="btn primary submit" type="submit" [disabled]="loading()">
          {{ loading() ? 'Criando conta…' : 'Criar conta' }}
        </button>
        <p class="switch-link">Já tem conta? <a routerLink="/login">Entrar</a></p>
      </form>
    </section>
  `,
  styles: [AUTH_STYLES],
})
export class RegisterComponent {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly loading = signal(false);
  readonly error = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    full_name: ['', [Validators.required, Validators.minLength(2)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.pattern(PASSWORD_PATTERN)]],
    organization_name: ['', [Validators.required, Validators.minLength(2)]],
  });

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.loading.set(true);
    this.error.set(null);
    this.auth.register(this.form.getRawValue()).subscribe({
      next: () => void this.router.navigate(['/dashboard']),
      error: (err: unknown) => {
        this.loading.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível criar a conta.'));
      },
    });
  }
}
