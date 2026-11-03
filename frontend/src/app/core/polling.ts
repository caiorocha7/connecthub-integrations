import { DestroyRef, inject } from '@angular/core';

/**
 * Runs `fn` every `intervalMs` while the page is visible, stopping automatically when the
 * component is destroyed. Returns a function to stop it manually.
 */
export function startPolling(fn: () => void, intervalMs: number): () => void {
  const destroyRef = inject(DestroyRef);
  const handle = setInterval(() => {
    if (typeof document === 'undefined' || document.visibilityState === 'visible') fn();
  }, intervalMs);
  const stop = () => clearInterval(handle);
  destroyRef.onDestroy(stop);
  return stop;
}
