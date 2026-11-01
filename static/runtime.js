/* Observe existing same-origin API calls without changing payloads or replaying writes. */
(() => {
  const owner = document.body.dataset.owner;
  if (!owner || !window.fetch) return;
  const nativeFetch = window.fetch.bind(window);
  const state = { reachable: null, session: 'active', saving: 0, failures: new Map(), accepted: false };
  window.WidgetDeckRuntime = { state };
  const feedback = document.createElement('p');
  feedback.id = 'pwa-save-feedback'; feedback.hidden = true;
  feedback.setAttribute('role', 'status'); feedback.setAttribute('aria-live', 'polite');
  const sessionNotice = document.createElement('aside');
  sessionNotice.id = 'pwa-session-status'; sessionNotice.hidden = true;
  sessionNotice.setAttribute('role', 'status'); sessionNotice.setAttribute('aria-live', 'polite');
  const sessionText = document.createElement('span');
  const signIn = document.createElement('a');
  signIn.textContent = 'Sign in in a new tab';
  signIn.target = '_blank'; signIn.rel = 'noopener noreferrer';
  signIn.href = '/login?' + new URLSearchParams({ next: location.pathname + location.search });
  const returnToApp = document.createElement('a');
  returnToApp.textContent = 'Open the current account'; returnToApp.href = '/'; returnToApp.hidden = true;
  sessionNotice.append(sessionText, signIn, returnToApp);
  document.body.append(feedback, sessionNotice);
  let feedbackTimer, checkInFlight;

  function reachable(value) {
    state.reachable = value;
    window.dispatchEvent(new CustomEvent('widgetdeck:connection', { detail: { reachable: value } }));
  }
  function saveState() {
    clearTimeout(feedbackTimer);
    const message = state.saving ? 'Saving…' : state.failures.size
      ? 'Some changes were not saved. Review this tool’s message before retrying.'
      : state.accepted ? 'Request accepted. Check this tool for completion.' : 'Saved';
    feedback.textContent = message; feedback.hidden = false;
    feedback.dataset.state = state.saving ? 'saving' : state.failures.size ? 'failed' : state.accepted ? 'accepted' : 'saved';
    window.dispatchEvent(new CustomEvent('widgetdeck:save-state', {
      detail: { state: feedback.dataset.state, message, pending: state.saving }
    }));
    if (!state.saving && !state.failures.size) feedbackTimer = setTimeout(() => { feedback.hidden = true; }, 1800);
  }
  function expired() {
    state.session = 'expired'; sessionNotice.hidden = false; signIn.hidden = false; returnToApp.hidden = true;
    sessionText.textContent = 'Your session expired. Keep this page open to preserve your edits, then sign in again. ';
    window.dispatchEvent(new Event('widgetdeck:session-expired'));
    document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    document.body.dataset.accountMismatch = 'true';
    signIn.focus({ preventScroll: true });
  }
  function accountChanged() {
    state.session = 'changed'; sessionNotice.hidden = false; signIn.hidden = true; returnToApp.hidden = false;
    sessionText.textContent = 'This tab belongs to a different account. Its workspace is hidden. ';
    window.dispatchEvent(new Event('widgetdeck:account-changed'));
    document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
    document.body.dataset.accountMismatch = 'true';
    returnToApp.focus({ preventScroll: true });
  }

  window.fetch = async (input, options) => {
    let url;
    try { url = new URL(typeof input === 'string' ? input : input.url || input.href, location.href); }
    catch (_) { return nativeFetch(input, options); }
    const credential = new Headers(options?.headers || input.headers).has('Authorization');
    const observed = url.origin === location.origin && url.pathname.includes('/api/') && !credential;
    if (!observed) return nativeFetch(input, options);
    const method = String(options?.method || input.method || 'GET').toUpperCase();
    const mutation = ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && url.pathname !== '/api/launcher/recent';
    const key = method + ' ' + url.pathname + url.search;
    if (mutation) {
      if (!state.saving) state.accepted = false;
      state.saving++; saveState();
    }
    try {
      const response = await nativeFetch(input, options);
      reachable(true);
      if (response.status === 401) expired();
      if (mutation) {
        if (response.ok) state.failures.delete(key);
        else state.failures.set(key, response.status);
        // A background job's acceptance is not proof that its content was saved.
        if (response.status === 202) state.accepted = true;
      }
      return response;
    } catch (error) {
      if (error.name !== 'AbortError') reachable(false);
      if (mutation) state.failures.set(key, error.name);
      throw error;
    } finally {
      if (mutation) {
        state.saving--;
        saveState();
      }
    }
  };

  async function checkSession() {
    if (document.hidden || checkInFlight) return;
    checkInFlight = (async () => {
      try {
        const response = await nativeFetch('/api/session', { cache: 'no-store' });
        reachable(true);
        if (response.status === 401) { expired(); return; }
        if (!response.ok) return;
        const data = await response.json();
        if (String(data.user_id) !== owner) { accountChanged(); return; }
        delete document.body.dataset.accountMismatch;
        const recovered = state.session !== 'active';
        state.session = 'active'; sessionNotice.hidden = true;
        window.dispatchEvent(new CustomEvent('widgetdeck:resume', { detail: { recovered } }));
      } catch (_) { reachable(false); }
    })();
    try { await checkInFlight; } finally { checkInFlight = null; }
  }
  window.WidgetDeckRuntime.checkSession = checkSession;
  document.addEventListener('visibilitychange', () => { if (!document.hidden) checkSession(); });
  window.addEventListener('pageshow', checkSession);
  window.addEventListener('online', checkSession);
  checkSession();
})();
