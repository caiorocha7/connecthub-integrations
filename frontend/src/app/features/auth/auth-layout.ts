/** Shared styles for login/register: split screen (product pitch + form panel). */
export const AUTH_STYLES = `
  :host { display: grid; grid-template-columns: 1.1fr 1fr; min-height: 100vh; }
  .panel { display: grid; place-items: center; padding: 40px 24px; background: var(--ch-surface); }
  .form-box { width: 100%; max-width: 380px; }
  .form-box h2 { font-size: 24px; margin-bottom: 6px; }
  .form-box .lead { color: var(--ch-text-2); margin: 0 0 28px; }
  .submit { width: 100%; height: 42px; margin-top: 8px; }
  .switch-link { text-align: center; margin-top: 20px; color: var(--ch-text-2); }
  .demo { margin-top: 24px; font-size: 12.5px; }
  @media (max-width: 900px) { :host { grid-template-columns: 1fr; } }
`;
