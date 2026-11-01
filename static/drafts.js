/* Recover text/structured edits after interruption; never submit or replay them. */
(() => {
  'use strict';
  const owner = document.body.dataset.owner;
  if (!owner) return;
  const prefix = `widgetdeck.draft.v1.${owner}.`, ttl = 7 * 86400000;
  const maxRecord = 512 * 1024, maxTotal = 2 * 1024 * 1024, maxRecords = 20;
  const controllers = new Set(), cleanup = new Set();
  let active = true;
  // A duplicated tab may inherit sessionStorage; each loaded editor needs its
  // own slot so concurrent copies cannot silently replace one another.
  const tab = crypto.randomUUID();
  const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
  const ownedKeys = () => Array.from({length:localStorage.length}, (_,i) => localStorage.key(i)).filter(key => key?.startsWith(prefix));
  function records() {
    return ownedKeys().flatMap(key => {
      try {
        const raw = localStorage.getItem(key);
        if (!raw || raw.length * 2 > maxRecord) return [];
        const record = JSON.parse(raw);
        if (record.owner !== owner || typeof record.resource !== 'string' || !Number.isFinite(record.savedAt) || record.savedAt > Date.now() + 60000 || !Object.hasOwn(record,'value') || !Object.hasOwn(record,'base')) return [];
        if (record.savedAt < Date.now() - ttl) { localStorage.removeItem(key); return []; }
        return [{...record,key,bytes:raw.length * 2}];
      } catch (_) { return []; } // Damaged data is retained, never replaced implicitly.
    });
  }
  function create({id, resource, read, restore, base, host, title = 'Recover unsaved edits', dirty = () => !same(read(),base()), validate = value => value !== undefined}) {
    if (!/^[a-z0-9-]+$/.test(id) || typeof resource !== 'string' || resource.length > 512) throw new Error('Invalid recovery resource.');
    const identity = id + ':' + resource, key = prefix + encodeURIComponent(identity) + '.' + tab;
    let disposed = false, restoredKey, timer, candidate;
    const panel = document.createElement('details'); panel.className = 'draft-recovery'; panel.dataset.draftGroup = id; panel.hidden = true;
    const summary = document.createElement('summary'); summary.textContent = title;
    const status = document.createElement('p'); status.setAttribute('role','status'); status.setAttribute('aria-live','polite');
    const recover = document.createElement('button'); recover.type = 'button'; recover.textContent = 'Restore draft';
    const discard = document.createElement('button'); discard.type = 'button'; discard.textContent = 'Discard recovery copy';
    const copy = document.createElement('textarea'); copy.readOnly = true; copy.hidden = true; copy.setAttribute('aria-label','Recovered draft to compare');
    panel.append(summary,status,recover,discard,copy); host.append(panel);
    const notice = message => { panel.hidden = false; panel.open = true; status.textContent = message; };
    function refresh() {
      if (disposed || !active) return;
      try {
        candidate = records().filter(record => record.resource === identity && validate(record.value)).sort((a,b) => b.savedAt - a.savedAt)[0];
        panel.hidden = !candidate; copy.hidden = true;
        recover.hidden = discard.hidden = !candidate;
        if (candidate) {
          status.textContent = 'Unsaved edits from ' + new Date(candidate.savedAt).toLocaleString() + '. Recovery stays in this browser for seven days; saving to your account is a separate action.';
          recover.disabled = !same(candidate.base,base());
          if (recover.disabled) { copy.value = JSON.stringify(candidate.value,null,2); copy.hidden = false; status.textContent += ' Saved content has changed. Compare/copy the recovered text before editing the current version.'; }
        }
      } catch (_) { notice('Draft recovery storage is unavailable. Keep this page open until your edits are saved.'); }
    }
    function capture() {
      clearTimeout(timer);
      if (disposed || !active || document.body.dataset.accountMismatch || !dirty()) return;
      try {
        const value = read(); if (!validate(value)) throw new Error('This edit cannot be recovered in its current format.');
        const currentBase = base(), previousRaw = localStorage.getItem(key);
        if (previousRaw) {
          let previous;
          try { previous = JSON.parse(previousRaw); }
          catch (_) { throw new Error('This recovery copy is damaged. Its original bytes have been retained.'); }
          if (previous.savedAt > Date.now()-ttl && same(previous.value,value) && same(previous.base,currentBase)) return;
        }
        const raw = JSON.stringify({owner, resource:identity, base:currentBase, value, savedAt:Date.now()});
        if (raw.length * 2 > maxRecord) throw new Error('This draft exceeds the recovery limit. Save it to your account or copy it before leaving.');
        records(); // Prune only expired valid records; retain malformed bytes.
        const others = ownedKeys().filter(existing => existing !== key);
        // Never evict another unexpired draft merely to make this one fit.
        if (others.length >= maxRecords || others.reduce((sum,existing)=>sum+(localStorage.getItem(existing)?.length || 0)*2,0) + raw.length * 2 > maxTotal) throw new Error('Draft recovery storage is full. Existing drafts are retained. Save or discard older recovery copies.');
        localStorage.setItem(key,raw);
      } catch (error) { notice(error.name === 'QuotaExceededError' || error.name === 'SecurityError' ? 'Browser storage is full or unavailable. Keep this page open or copy your edits before leaving.' : error.message); }
    }
    function clear() {
      clearTimeout(timer);
      try { localStorage.removeItem(key); if (restoredKey) localStorage.removeItem(restoredKey); refresh(); }
      catch (_) { notice('Could not remove the recovery copy. Your account save is unaffected.'); }
    }
    recover.addEventListener('click', () => {
      if (!active || document.body.dataset.accountMismatch) return;
      refresh(); if (!candidate || recover.disabled) return;
      if (dirty() && !confirm('Replace the current unsaved edits with this recovery draft?')) return;
      restoredKey = candidate.key; restore(JSON.parse(JSON.stringify(candidate.value))); capture();
      notice('Draft restored. Review it, then save explicitly to your account.');
    });
    discard.addEventListener('click', () => {
      if (!active || !candidate || !confirm('Discard this recovery copy? Current editor values will stay unchanged.')) return;
      try { localStorage.removeItem(candidate.key); refresh(); } catch (_) { notice('Could not discard the recovery copy.'); }
    });
    const controller = {capture, clear, refresh, changed() {clearTimeout(timer); timer = setTimeout(capture,250);}, dispose({preserve = true} = {}) {if(preserve)capture(); disposed = true; clearTimeout(timer); controllers.delete(controller); panel.remove();}};
    controllers.add(controller); refresh(); return controller;
  }
  function preserve() { controllers.forEach(controller => controller.capture()); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) preserve(); });
  window.addEventListener('pagehide',preserve);
  window.addEventListener('widgetdeck:session-expired', () => {preserve(); active = false;});
  window.addEventListener('widgetdeck:account-changed', () => {preserve(); active = false;});
  window.addEventListener('widgetdeck:resume', () => {active = !document.body.dataset.accountMismatch; if (active) controllers.forEach(controller=>controller.refresh());});
  window.addEventListener('storage', event => {if (event.key?.startsWith(prefix)) controllers.forEach(controller=>controller.refresh());});
  document.querySelector('form.logout')?.addEventListener('submit', () => {
    active = false;
    try { ownedKeys().forEach(key => localStorage.removeItem(key)); cleanup.forEach(callback=>{try{callback();}catch(_){}}); }
    catch (_) { /* Do not block signing out if storage was disabled. */ }
  });
  window.WidgetDeckDrafts = {create, onLogout(callback) {cleanup.add(callback); return ()=>cleanup.delete(callback);}, limits:{ttl,maxRecord,maxTotal,maxRecords}};
})();
