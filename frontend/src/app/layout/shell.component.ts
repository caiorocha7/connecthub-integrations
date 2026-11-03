import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { filter } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import { AuthService } from '../core/auth.service';
import { IconComponent } from '../shared/icon.component';

interface NavItem {
  path: string;
  label: string;
  icon: string;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

@Component({
  selector: 'ch-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, IconComponent],
  template: `
    <div class="shell" [class.nav-open]="navOpen()">
      <aside class="sidebar">
        <a class="brand" routerLink="/dashboard">
          <span class="logo">
            <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
              <rect width="32" height="32" rx="8" fill="#5b5bf0" />
              <circle cx="10" cy="16" r="3.5" fill="#fff" />
              <circle cx="22" cy="10" r="3" fill="#14b8a6" />
              <circle cx="22" cy="22" r="3" fill="#14b8a6" />
              <path
                d="M13 15l6-4M13 17l6 4"
                stroke="#fff"
                stroke-width="2"
                stroke-linecap="round"
              />
            </svg>
          </span>
          <span class="brand-text">Connect<b>Hub</b></span>
        </a>

        <nav>
          @for (group of nav; track group.title) {
            <div class="nav-group">{{ group.title }}</div>
            @for (item of group.items; track item.path) {
              <a [routerLink]="item.path" routerLinkActive="active" class="nav-item">
                <ch-icon [name]="item.icon" [size]="17" />
                <span>{{ item.label }}</span>
              </a>
            }
          }
        </nav>

        <div class="sidebar-footer">
          <a href="/docs" target="_blank" rel="noopener" class="nav-item">
            <ch-icon name="book" [size]="17" /><span>API · OpenAPI</span>
          </a>
        </div>
      </aside>
      <div class="scrim" (click)="navOpen.set(false)"></div>

      <div class="main">
        <header class="topbar">
          <button
            class="btn ghost icon menu-btn"
            (click)="navOpen.set(!navOpen())"
            aria-label="Abrir menu"
          >
            <ch-icon name="menu" />
          </button>
          <div class="org-switch">
            <span class="org-avatar">{{ orgInitials() }}</span>
            <select
              class="input sm"
              [value]="auth.currentOrgId()"
              (change)="switchOrg($event)"
              aria-label="Organização atual"
            >
              @for (m of auth.memberships(); track m.organization_id) {
                <option [value]="m.organization_id">{{ m.organization_name }}</option>
              }
            </select>
            @if (auth.currentMembership(); as m) {
              <span class="badge plain" [class.primary]="m.role === 'ADMIN'">{{ m.role }}</span>
            }
          </div>
          <div class="spacer"></div>
          <div class="user">
            <div class="user-meta">
              <span class="user-name">{{ auth.user()?.full_name }}</span>
              <span class="user-email">{{ auth.user()?.email }}</span>
            </div>
            <span class="avatar">{{ userInitials() }}</span>
            <button class="btn ghost icon" (click)="auth.logout()" title="Sair" aria-label="Sair">
              <ch-icon name="logout" />
            </button>
          </div>
        </header>
        <main>
          @if (auth.currentOrgId(); as orgId) {
            @for (key of [orgId]; track key) {
              <router-outlet />
            }
          }
        </main>
      </div>
    </div>
  `,
  styles: [
    `
      .shell {
        display: flex;
        min-height: 100vh;
      }
      .sidebar {
        width: 248px;
        flex-shrink: 0;
        background: linear-gradient(180deg, var(--ch-ink-950), var(--ch-ink-900));
        color: var(--ch-ink-300);
        display: flex;
        flex-direction: column;
        position: sticky;
        top: 0;
        height: 100vh;
        z-index: 50;
      }
      .brand {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 20px 20px 18px;
        color: #fff;
        text-decoration: none;
      }
      .brand-text {
        font-size: 18px;
        font-weight: 600;
        letter-spacing: -0.02em;
      }
      .brand-text b {
        color: #8f8ff8;
        font-weight: 700;
      }
      nav {
        flex: 1;
        overflow-y: auto;
        padding: 4px 12px;
      }
      .nav-group {
        font-size: 10.5px;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: var(--ch-ink-500);
        padding: 16px 10px 6px;
        font-weight: 600;
      }
      .nav-item {
        display: flex;
        align-items: center;
        gap: 11px;
        padding: 9px 10px;
        border-radius: 8px;
        color: var(--ch-ink-300);
        font-weight: 500;
        text-decoration: none;
        transition:
          background 0.15s,
          color 0.15s;
      }
      .nav-item:hover {
        background: rgba(255, 255, 255, 0.05);
        color: #fff;
        text-decoration: none;
      }
      .nav-item.active {
        background: rgba(91, 91, 240, 0.18);
        color: #fff;
        box-shadow: inset 2px 0 0 #8f8ff8;
      }
      .sidebar-footer {
        padding: 12px;
        border-top: 1px solid rgba(255, 255, 255, 0.06);
      }
      .main {
        flex: 1;
        min-width: 0;
        display: flex;
        flex-direction: column;
      }
      .topbar {
        height: 64px;
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 0 24px;
        background: rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(8px);
        border-bottom: 1px solid var(--ch-border);
        position: sticky;
        top: 0;
        z-index: 40;
      }
      .org-switch {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .org-switch select {
        min-width: 200px;
        font-weight: 600;
      }
      .org-avatar,
      .avatar {
        width: 32px;
        height: 32px;
        border-radius: 9px;
        display: grid;
        place-items: center;
        font-weight: 700;
        font-size: 12px;
        background: var(--ch-accent-50);
        color: #0f8f82;
        flex-shrink: 0;
      }
      .avatar {
        border-radius: 50%;
        background: var(--ch-primary-50);
        color: var(--ch-primary);
      }
      .user {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .user-meta {
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        line-height: 1.2;
      }
      .user-name {
        font-weight: 600;
        font-size: 13px;
      }
      .user-email {
        font-size: 11.5px;
        color: var(--ch-text-3);
      }
      .menu-btn {
        display: none;
      }
      .scrim {
        display: none;
      }
      @media (max-width: 960px) {
        .sidebar {
          position: fixed;
          left: 0;
          transform: translateX(-100%);
          transition: transform 0.2s;
        }
        .nav-open .sidebar {
          transform: none;
        }
        .nav-open .scrim {
          display: block;
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.4);
          z-index: 45;
        }
        .menu-btn {
          display: inline-flex;
        }
        .user-meta {
          display: none;
        }
        .topbar {
          padding: 0 12px;
        }
        .org-switch select {
          min-width: 0;
          max-width: 160px;
        }
      }
    `,
  ],
})
export class ShellComponent {
  readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  readonly navOpen = signal(false);

  readonly nav: NavGroup[] = [
    {
      title: 'Monitoramento',
      items: [{ path: '/dashboard', label: 'Dashboard', icon: 'dashboard' }],
    },
    {
      title: 'Integrações',
      items: [
        { path: '/endpoints', label: 'Endpoints', icon: 'endpoint' },
        { path: '/destinations', label: 'Destinos', icon: 'destination' },
        { path: '/transforms', label: 'Transformações', icon: 'transform' },
      ],
    },
    {
      title: 'Operação',
      items: [
        { path: '/events', label: 'Eventos', icon: 'events' },
        { path: '/deliveries', label: 'Entregas', icon: 'deliveries' },
        { path: '/failures', label: 'Falhas & reprocesso', icon: 'failures' },
        { path: '/simulator', label: 'Simulador', icon: 'simulator' },
      ],
    },
    {
      title: 'Administração',
      items: [
        { path: '/organization', label: 'Organização', icon: 'org' },
        { path: '/settings', label: 'Configurações', icon: 'settings' },
      ],
    },
  ];

  readonly orgInitials = computed(() =>
    initials(this.auth.currentMembership()?.organization_name ?? '?'),
  );
  readonly userInitials = computed(() => initials(this.auth.user()?.full_name ?? '?'));

  constructor() {
    this.router.events
      .pipe(
        filter((e) => e instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.navOpen.set(false));
  }

  switchOrg(event: Event): void {
    const orgId = (event.target as HTMLSelectElement).value;
    this.auth.selectOrg(orgId);
    void this.router.navigate(['/dashboard']);
  }
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join('');
}
