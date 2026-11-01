(() => {
  const notice = document.createElement('aside');
  notice.id = 'pwa-connection';
  notice.setAttribute('role', 'status');
  notice.setAttribute('aria-live', 'polite');
  notice.hidden = true;
  notice.textContent = 'Your device reports no connection. Check your connection before saving.';
  document.body.append(notice);
  function connectionChanged() {
    const reachable = window.WidgetDeckRuntime?.state.reachable;
    notice.hidden = reachable === true || (reachable !== false && navigator.onLine);
    notice.textContent = reachable === false
      ? 'The server could not be reached. Changes have not been queued. Reconnect and retry.'
      : 'Your device reports no connection. Check your connection before saving.';
  }
  window.addEventListener('online', connectionChanged);
  window.addEventListener('offline', () => {
    if (window.WidgetDeckRuntime) window.WidgetDeckRuntime.state.reachable = null;
    connectionChanged();
  });
  window.addEventListener('widgetdeck:connection', connectionChanged);
  connectionChanged();
  if ('serviceWorker' in navigator && window.isSecureContext) {
    const update = document.createElement('aside');
    update.id = 'pwa-update';
    update.setAttribute('role', 'status');
    update.hidden = true;
    const text = document.createElement('span');
    text.textContent = 'An update is ready. Save your work, then reload.';
    const reload = document.createElement('button');
    reload.type = 'button';
    reload.textContent = 'Reload to update';
    update.append(text, reload);
    document.body.append(update);
    let registration, requested = false;
    reload.addEventListener('click', () => {
      if (!registration?.waiting) return;
      if (!confirm('Reload WidgetDeck to apply the update? Save any unsaved work first.')) return;
      requested = true;
      reload.disabled = true;
      registration.waiting.postMessage({ type: 'WIDGETDECK_ACTIVATE' });
    });
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      // Another tab may activate the new worker. Never reload that tab's editors.
      if (requested) location.reload();
    });
    navigator.serviceWorker.register('/service-worker.js', { scope: '/', updateViaCache: 'none' })
      .then(value => {
        registration = value;
        const showWaiting = () => { update.hidden = !registration.waiting || !navigator.serviceWorker.controller; };
        showWaiting();
        registration.addEventListener('updatefound', () => {
          registration.installing?.addEventListener('statechange', showWaiting);
        });
        document.addEventListener('visibilitychange', () => {
          if (!document.hidden) registration.update().catch(() => {});
        });
      })
      .catch(() => { /* The online application remains usable if installation fails. */ });
  }
})();
