/* Account-scoped browser saves. Never infer ownership of unowned legacy data. */
(() => {
  'use strict';
  const owner = document.body.dataset.owner;
  if (!owner) return;
  let active = true;
  window.addEventListener('widgetdeck:session-expired', () => { active = false; });
  window.addEventListener('widgetdeck:account-changed', () => { active = false; });
  window.addEventListener('widgetdeck:resume', () => { active = !document.body.dataset.accountMismatch; });
  const copy = value => JSON.parse(JSON.stringify(value));
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  function merge(current, older, kind) {
    if (current === undefined) return {value: older, conflicts: 0};
    if (kind === 'map') {
      const conflicts = Object.keys(older).filter(key => Object.hasOwn(current, key) && !same(current[key], older[key])).length;
      return {value: {...older, ...current}, conflicts};
    }
    if (kind === 'list') {
      const byId = new Map(current.filter(item => item?.id !== undefined).map(item => [item.id, item]));
      const extra = [], exact = new Set(current.map(item => JSON.stringify(item)));
      let conflicts = 0;
      for (const item of older) {
        if (item?.id !== undefined && byId.has(item.id)) {
          if (!same(byId.get(item.id), item)) conflicts++;
        } else if (!exact.has(JSON.stringify(item))) {
          extra.push(item); exact.add(JSON.stringify(item));
        }
      }
      return {value: [...current, ...extra], conflicts};
    }
    return {value: current, conflicts: same(current, older) ? 0 : 1};
  }
  function create({id, title, records, host, onRecovered}) {
    if (!/^[a-z0-9-]+$/.test(id)) throw new Error('Invalid browser save group.');
    const definitions = new Map(records.map(record => [record.key, record]));
    const prefix = 'widgetdeck.account.' + owner + '.';
    const claimKey = 'widgetdeck.legacy-owner.v1.' + id;
    const backupKey = 'widgetdeck.legacy-backup.v1.' + id;
    const lockKey = 'widgetdeck.storage.v1.' + id;
    let queue = Promise.resolve(), message = '', failed = false;
    const panel = document.createElement('details');
    panel.className = 'account-storage-panel'; panel.dataset.storageGroup = id;
    const summary = document.createElement('summary'); summary.textContent = title + ' browser saves';
    const explanation = document.createElement('p'); explanation.setAttribute('role', 'status');
    const recoverButton = document.createElement('button'); recoverButton.type = 'button';
    recoverButton.textContent = 'Recover my older saves';
    const backupButton = document.createElement('button'); backupButton.type = 'button';
    backupButton.textContent = 'Download data backup';
    panel.append(summary, explanation, recoverButton, backupButton);
    function place() {
      if (host && (host.tagName !== 'DIALOG' || host.open)) { if (panel.parentElement !== host) host.append(panel); }
      else if (panel.nextElementSibling !== document.querySelector('main')) document.querySelector('main')?.before(panel);
    }
    place();
    if (host?.tagName === 'DIALOG') new MutationObserver(place).observe(host, {attributes:true, attributeFilter:['open']});
    function ensureActive() {
      if (!active || document.body.dataset.accountMismatch) throw new Error('Sign back into this account before saving browser data.');
    }
    function parse(key, raw) {
      const record = definitions.get(key);
      if (!record) throw new Error('Unknown browser save record.');
      let value;
      try { value = JSON.parse(raw); } catch (_) { throw new Error('Saved data is damaged or has an unsupported format. It has not been overwritten.'); }
      if (!record.validate(value)) throw new Error('Saved data is damaged or has an unsupported format. It has not been overwritten.');
      return value;
    }
    function claim() {
      const raw = localStorage.getItem(claimKey);
      if (raw === null) return null;
      const value = JSON.parse(raw);
      if (typeof value?.owner !== 'string' || !['pending', 'done'].includes(value.state)) throw new Error('The older-data recovery record is damaged. Existing data has not been changed.');
      return value;
    }
    function render() {
      try {
        const savedClaim = claim(), mine = savedClaim?.owner === owner;
        const legacy = records.some(record => localStorage.getItem(record.key) !== null);
        const ownData = records.some(record => localStorage.getItem(prefix + record.key) !== null);
        panel.hidden = !message && !legacy && !savedClaim;
        explanation.textContent = message || (mine && savedClaim.state === 'done'
          ? 'Older saves were recovered for this account. Your original data is retained as a backup.'
          : savedClaim && !mine ? 'Older browser saves have already been recovered by another account.'
          : 'Older saved data is available in this browser. Recover it only if it belongs to you. New saves belong to your signed-in account.');
        recoverButton.textContent = mine && savedClaim.state === 'pending' ? 'Finish recovery' : 'Recover my older saves';
        recoverButton.hidden = !legacy || Boolean(savedClaim && (!mine || savedClaim.state === 'done'));
        backupButton.hidden = !ownData && !mine;
        panel.dataset.error = String(failed);
        if (failed || (legacy && !savedClaim) || (mine && savedClaim.state === 'pending')) panel.open = true;
      } catch (_) {
        panel.hidden = false; panel.open = true; panel.dataset.error = 'true';
        explanation.textContent = 'Browser save storage is unavailable or its recovery record is damaged. Existing data has not been overwritten.';
        recoverButton.hidden = true; backupButton.hidden = true;
      }
    }
    function explain(error) {
      if (['QuotaExceededError', 'SecurityError'].includes(error.name)) return 'Browser storage is full or unavailable. Existing data is retained. Free space and try again.';
      if (error.name === 'SyntaxError') return 'A browser data recovery record is damaged. Existing data is retained.';
      return error.message || 'Browser data could not be saved or recovered. Existing data is retained.';
    }
    function notice(text, error = true) { message = text; failed = error; render(); }
    function locked(task, requireLocks = false) {
      if (navigator.locks?.request) return navigator.locks.request(lockKey, task);
      if (requireLocks) return Promise.reject(new Error('Older-data recovery requires browser storage locks. Open this app over HTTPS in a browser that supports them. Existing data is unchanged.'));
      const pending = queue.then(task); queue = pending.catch(() => {}); return pending;
    }
    async function authenticate() {
      ensureActive();
      const response = await fetch('/api/session', {cache: 'no-store'});
      if (!response.ok || String((await response.json()).user_id) !== owner) throw new Error('Sign back into this account before recovering or exporting browser data.');
      ensureActive();
    }
    function readValue(key) {
      const raw = localStorage.getItem(prefix + key), savedClaim = claim();
      const current = raw === null ? undefined : parse(key, raw);
      if (savedClaim?.owner === owner && savedClaim.state === 'pending') {
        const olderRaw = savedClaim.backedUp ? JSON.parse(localStorage.getItem(backupKey))?.[key] : localStorage.getItem(key);
        if (typeof olderRaw === 'string') return merge(current, parse(key, olderRaw), definitions.get(key).kind).value;
      }
      return current;
    }
    function read(key, fallback) {
      try {
        ensureActive(); const value = readValue(key);
        return value === undefined ? copy(fallback) : value;
      } catch (error) { notice(explain(error)); return copy(fallback); }
    }
    async function update(key, updater) {
      try {
        return await locked(() => {
          ensureActive();
          const record = definitions.get(key), savedClaim = claim();
          if (savedClaim?.owner === owner && savedClaim.state === 'pending' && !savedClaim.backedUp) throw new Error('Finish recovery before changing these saves. Older data remains readable and can be downloaded as a backup.');
          const current = readValue(key);
          const value = updater(current === undefined ? copy(record.initial) : current);
          if (!record.validate(value)) throw new Error('The new browser save has an unsupported format. Existing data is unchanged.');
          localStorage.setItem(prefix + key, JSON.stringify(value));
          return true;
        });
      } catch (error) { notice(explain(error)); return false; }
    }
    async function recover() {
      try {
        const result = await locked(async () => {
          await authenticate();
          let savedClaim = claim();
          if (savedClaim && savedClaim.owner !== owner) throw new Error('Older browser saves belong to another account.');
          if (savedClaim?.state === 'done') return {conflicts: 0};
          let originals;
          if (savedClaim?.backedUp) {
            originals = JSON.parse(localStorage.getItem(backupKey));
            if (!originals || typeof originals !== 'object' || Array.isArray(originals)) throw new Error('The older-data backup is unavailable. Existing saves are unchanged.');
          } else {
            originals = Object.fromEntries(records.map(record => [record.key, localStorage.getItem(record.key)]));
          }
          const pending = [];
          let conflicts = 0;
          for (const record of records) {
            const raw = originals[record.key];
            if (raw === null) continue;
            if (typeof raw !== 'string') throw new Error('The older-data backup is damaged. Existing saves are unchanged.');
            const older = parse(record.key, raw), currentRaw = localStorage.getItem(prefix + record.key);
            const current = currentRaw === null ? undefined : parse(record.key, currentRaw);
            const merged = merge(current, older, record.kind);
            if (!record.validate(merged.value)) throw new Error('Older data could not be merged safely. Existing saves are unchanged.');
            conflicts += merged.conflicts; pending.push([prefix + record.key, JSON.stringify(merged.value)]);
          }
          if (!savedClaim) {
            savedClaim = {owner, state: 'pending', backedUp:false};
            localStorage.setItem(claimKey, JSON.stringify(savedClaim));
          }
          if (!savedClaim.backedUp) {
            // Reserve first: even a backup-quota failure leaves this owner's original
            // saves readable. No account record changes until the backup is durable.
            localStorage.setItem(backupKey, JSON.stringify(originals));
            savedClaim = {...savedClaim, backedUp:true};
            localStorage.setItem(claimKey, JSON.stringify(savedClaim));
          }
          // All new writes use this same lock. A partial quota failure is retryable by
          // this owner only; merging again retains newer account records and IDs.
          for (const [key, raw] of pending) localStorage.setItem(key, raw);
          localStorage.setItem(claimKey, JSON.stringify({...savedClaim, state: 'done'}));
          return {conflicts};
        }, true);
        await onRecovered?.();
        notice(result.conflicts
          ? 'Recovery complete. Existing saved items were kept where IDs conflicted. The original older versions are available in the data backup.'
          : 'Recovery complete. Your older saves are available in this account; original data is retained as a backup.', false);
        return true;
      } catch (error) {
        try { if (claim()?.owner === owner) await onRecovered?.(); } catch (_) { /* Keep the original recovery failure visible. */ }
        notice(explain(error)); return false;
      }
    }
    async function downloadBackup() {
      try {
        await authenticate();
        const data = {schema_version: 1, account: owner, records: Object.fromEntries(records.map(record => [record.key, localStorage.getItem(prefix + record.key)]))};
        const savedClaim=claim();
        if (savedClaim?.owner === owner) data.older = savedClaim.backedUp ? JSON.parse(localStorage.getItem(backupKey)) : Object.fromEntries(records.map(record=>[record.key,localStorage.getItem(record.key)]));
        const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'}));
        const link = document.createElement('a'); link.href = url; link.download = id + '-browser-backup.json'; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      } catch (error) { notice(explain(error)); }
    }
    recoverButton.addEventListener('click', async () => {
      if (!confirm('Recover this browser’s older ' + title + ' saves into your account? Continue only if these older saves belong to you.')) return;
      recoverButton.disabled = true;
      try { await recover(); } finally { recoverButton.disabled = false; }
    });
    backupButton.addEventListener('click', downloadBackup);
    window.addEventListener('storage', event => { if ([claimKey, backupKey].includes(event.key)) render(); });
    render();
    return {read, update, write: (key, value) => update(key, () => value), recover, key: key => prefix + key};
  }
  window.WidgetDeckStorage = {create};
})();
