(() => {
  const notice = document.createElement('aside');
  notice.id = 'pwa-connection';
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  notice.hidden = true;
  notice.textContent = 'Connection unavailable. Changes cannot be saved. Reconnect before continuing.';
  document.body.append(notice);
  function connectionChanged() { notice.hidden = navigator.onLine; }
  window.addEventListener('online', connectionChanged);
  window.addEventListener('offline', connectionChanged);
  connectionChanged();
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/service-worker.js', { scope: '/', updateViaCache: 'none' })
      .catch(() => { /* The online application remains usable if installation fails. */ });
  }
})();
