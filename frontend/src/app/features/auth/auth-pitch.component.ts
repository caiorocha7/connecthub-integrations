import { ChangeDetectionStrategy, Component } from '@angular/core';

@Component({
  selector: 'ch-auth-pitch',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="pitch">
      <div class="brand">
        <svg viewBox="0 0 32 32" width="34" height="34" aria-hidden="true">
          <rect width="32" height="32" rx="8" fill="#5b5bf0" />
          <circle cx="10" cy="16" r="3.5" fill="#fff" />
          <circle cx="22" cy="10" r="3" fill="#14b8a6" />
          <circle cx="22" cy="22" r="3" fill="#14b8a6" />
          <path d="M13 15l6-4M13 17l6 4" stroke="#fff" stroke-width="2" stroke-linecap="round" />
        </svg>
        <span>Connect<b>Hub</b></span>
      </div>
      <div>
        <h1>Integrações que não perdem eventos — nem quando o destino cai.</h1>
        <p>
          Receba webhooks assinados, transforme payloads sem código e entregue com retentativas,
          idempotência e rastreabilidade completa.
        </p>
        <ul class="features">
          <li>
            <span class="dot">✓</span>
            <span
              ><b>HMAC + proteção contra replay</b><br />Cada evento é autenticado pelo corpo
              bruto.</span
            >
          </li>
          <li>
            <span class="dot">✓</span>
            <span
              ><b>Outbox transacional</b><br />Evento persistido nunca fica sem ser
              enfileirado.</span
            >
          </li>
          <li>
            <span class="dot">✓</span>
            <span
              ><b>Backoff exponencial com jitter</b><br />429, 5xx e timeouts tratados
              automaticamente.</span
            >
          </li>
        </ul>
      </div>
      <div class="flow">
        <span>Webhook</span>→<span>API</span>→<span>PostgreSQL + Outbox</span
        >→<span>Redis</span>→<span>Worker</span>→<span>Destino</span>
      </div>
    </section>
  `,
  styles: [
    `
      :host {
        display: contents;
      }
      .pitch {
        background:
          radial-gradient(1200px 500px at -10% -10%, #2b2f7a 0%, transparent 60%),
          radial-gradient(800px 400px at 110% 110%, #0f766e 0%, transparent 55%), var(--ch-ink-950);
        color: #fff;
        padding: 56px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        gap: 32px;
      }
      .brand {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 20px;
        font-weight: 600;
      }
      .brand b {
        color: #8f8ff8;
      }
      h1 {
        font-size: 34px;
        line-height: 1.15;
        max-width: 480px;
        letter-spacing: -0.03em;
      }
      p {
        color: var(--ch-ink-300);
        max-width: 460px;
        font-size: 15px;
      }
      .features {
        list-style: none;
        padding: 0;
        margin: 28px 0 0;
        display: grid;
        gap: 14px;
      }
      .features li {
        display: flex;
        gap: 12px;
        align-items: flex-start;
        color: #d8dbf0;
      }
      .dot {
        width: 26px;
        height: 26px;
        border-radius: 8px;
        display: grid;
        place-items: center;
        background: rgba(143, 143, 248, 0.15);
        color: #a5a5ff;
        flex-shrink: 0;
      }
      .flow {
        display: flex;
        align-items: center;
        gap: 10px;
        font-family: var(--ch-mono);
        font-size: 12px;
        color: var(--ch-ink-300);
        flex-wrap: wrap;
      }
      .flow span {
        padding: 6px 10px;
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.04);
      }
      @media (max-width: 900px) {
        .pitch {
          display: none;
        }
      }
    `,
  ],
})
export class AuthPitchComponent {}
