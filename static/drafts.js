/* Recover text/structured edits after interruption; never submit or replay them. */
(() => {
  'use strict';
  const owner = document.body.dataset.owner;
  if (!owner) return;
  const prefix = `widgetdeck.draft.v1.${owner}.`, ttl = 7 * 86400000;
  const receiptPrefix = `widgetdeck.draft.receipt.${owner}.`;
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
  function create({id, resource, read, restore, base, host, title = 'Recover unsaved edits', dirty = () => !same(read(),base()), validate = value => value !== undefined, canRestore = () => true}) {
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
        const raw = JSON.stringify({owner, resource:identity, base:currentBase, value, savedAt:Date.now(),version:crypto.randomUUID()});
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
      if (!canRestore()) {notice('Wait for the current request to finish before restoring a draft.');return;}
      if (dirty() && !confirm('Replace the current unsaved edits with this recovery draft?')) return;
      try {
        restoredKey = candidate.key; restore(JSON.parse(JSON.stringify(candidate.value))); capture();
        notice('Draft restored. Review it, then save explicitly to your account.');
      } catch (_) { copy.value=JSON.stringify(candidate.value,null,2);copy.hidden=false;notice('Could not apply this draft to the current form. Its recovery copy is retained for comparison.'); }
    });
    discard.addEventListener('click', () => {
      if (!active || !candidate || !confirm('Discard this recovery copy? Current editor values will stay unchanged.')) return;
      try { localStorage.removeItem(candidate.key); refresh(); } catch (_) { notice('Could not discard the recovery copy.'); }
    });
    function receipt() {
      const keys=Array.from({length:sessionStorage.length},(_,i)=>sessionStorage.key(i)).filter(existing=>existing?.startsWith(receiptPrefix));
      keys.forEach(existing=>{try{if(JSON.parse(sessionStorage.getItem(existing)).createdAt<Date.now()-86400000)sessionStorage.removeItem(existing);}catch(_){}});
      if(keys.filter(existing=>sessionStorage.getItem(existing)!==null).length>=20)throw new Error('Too many pending form receipts.');
      const nonce=crypto.randomUUID();
      const draftKeys=[key,restoredKey].filter(Boolean);
      const versions=Object.fromEntries(draftKeys.map(existing=>[existing,JSON.parse(localStorage.getItem(existing))?.version??null]));
      sessionStorage.setItem(receiptPrefix+nonce,JSON.stringify({resource:identity,keys:draftKeys,versions,createdAt:Date.now()}));
      return nonce;
    }
    function acknowledge() {
      const url=new URL(location.href),nonce=url.searchParams.get('_draft_ack');
      if(!nonce)return;
      try {
        const record=JSON.parse(sessionStorage.getItem(receiptPrefix+nonce));
        if(record?.resource!==identity || record.createdAt<Date.now()-86400000 || !Array.isArray(record.keys) || !record.keys.every(existing=>existing.startsWith(prefix+encodeURIComponent(identity)+'.')))return;
        record.keys.forEach(existing=>{const current=JSON.parse(localStorage.getItem(existing));if((current?.version??null)===(record.versions?.[existing]??null))localStorage.removeItem(existing);});sessionStorage.removeItem(receiptPrefix+nonce);
        url.searchParams.delete('_draft_ack');history.replaceState(history.state,'',url);
      } catch (_) { /* An absent/broken receipt must not discard a draft. */ }
    }
    const controller = {capture, clear, refresh, receipt, changed() {clearTimeout(timer); timer = setTimeout(capture,250);}, dispose({preserve = true} = {}) {if(preserve)capture(); disposed = true; clearTimeout(timer); controllers.delete(controller); panel.remove();}};
    acknowledge();
    controllers.add(controller); refresh(); return controller;
  }
  function bindForm(form,{prepareRestore}={}) {
    const controls=()=>[...form.elements].filter(field=>field.name && field.matches('input:not([type=hidden],[type=password],[type=file],[type=submit],[type=button]),textarea,select') && !field.closest('.draft-recovery'));
    const read=()=>controls().map(field=>({name:field.name,value:field.value,checked:field.matches('[type=checkbox],[type=radio]')?field.checked:null}));
    const baseline=read();
    const controller=create({id:'native-form',resource:new URL(form.action).pathname+':'+form.dataset.draftForm,host:form,base:()=>baseline,read,
      dirty:()=>!same(read(),baseline),
      validate:value=>Array.isArray(value) && value.length<=200 && value.every(field=>typeof field?.name==='string' && field.name.length<=80 && typeof field.value==='string' && field.value.length<=100000 && (field.checked===null || typeof field.checked==='boolean')),
      restore:value=>{
        prepareRestore?.(value);
        const fields=controls();
        if(fields.length!==value.length || fields.some((field,index)=>field.name!==value[index].name))throw new Error('The form fields changed.');
        fields.forEach((field,index)=>{field.value=value[index].value;if(value[index].checked!==null)field.checked=value[index].checked;});
        fields.forEach(field=>field.dispatchEvent(new Event('input',{bubbles:true})));
      }
    });
    form.addEventListener('input',event=>{if(!event.target.closest('.draft-recovery'))controller.changed();});
    form.addEventListener('change',event=>{if(!event.target.closest('.draft-recovery'))controller.changed();});
    form.addEventListener('click',event=>{if(event.target.closest('button')&&!event.target.closest('.draft-recovery'))controller.changed();});
    form.addEventListener('submit',event=>{
      if(event.defaultPrevented)return;
      controller.capture();
      try {
        let token=form.querySelector('input[name=_draft_token]');
        if(!token){token=document.createElement('input');token.type='hidden';token.name='_draft_token';form.append(token);}
        token.value=controller.receipt();
      }catch(_){ /* A failed receipt retains the draft even if the native save succeeds. */ }
    });
    return controller;
  }
  function preserve() { controllers.forEach(controller => controller.capture()); }
  document.addEventListener('visibilitychange', () => { if (document.hidden) preserve(); });
  window.addEventListener('pagehide',preserve);
  window.addEventListener('widgetdeck:session-expired', () => {preserve(); active = false;});
  window.addEventListener('widgetdeck:account-changed', () => {preserve(); active = false;});
  window.addEventListener('widgetdeck:resume', () => {active = !document.body.dataset.accountMismatch; if (active) controllers.forEach(controller=>controller.refresh());});
  window.addEventListener('storage', event => {if (event.key?.startsWith(prefix)) controllers.forEach(controller=>controller.refresh());});
  document.querySelector('form.logout')?.addEventListener('submit', event => {
    if(event.defaultPrevented)return;
    active = false;
    try { ownedKeys().forEach(key => localStorage.removeItem(key));
      for(const store of [localStorage,sessionStorage]){
        const metadataKeys=Array.from({length:store.length},(_,i)=>store.key(i)).filter(key=>key?.startsWith('widgetdeck.draft-retention.'+owner+'.'));
        for(const key of metadataKeys){try{const descriptors=decodeURIComponent(key.slice(('widgetdeck.draft-retention.'+owner+'.').length)).split(':').slice(1).join(':').split('|');const times=JSON.parse(store.getItem(key));for(const draftKey of Object.keys(times))if(descriptors.some(prefix=>prefix.includes(owner)&&(draftKey===prefix||(/[.:]$/.test(prefix)&&draftKey.startsWith(prefix)))))store.removeItem(draftKey);store.removeItem(key);}catch(_){}}
      }
      cleanup.forEach(callback=>{try{callback();}catch(_){}}); }
    catch (_) { /* Do not block signing out if storage was disabled. */ }
    try { Array.from({length:sessionStorage.length},(_,i)=>sessionStorage.key(i)).filter(key=>key?.startsWith(receiptPrefix)).forEach(key=>sessionStorage.removeItem(key)); }catch(_){}
  });
  // Keep supported older draft bytes intact; store retention metadata separately.
  // Callers supply only prefixes that already include the verified account ID.
  function storage({prefixes,area='local'}) {
    if(!Array.isArray(prefixes)||!prefixes.length||prefixes.some(value=>typeof value!=='string'||!value.includes(owner)))throw new Error('Account-scoped draft prefixes required.');
    const store=area==='session'?sessionStorage:localStorage;
    const metaKey='widgetdeck.draft-retention.'+owner+'.'+encodeURIComponent(area+':'+prefixes.join('|'));
    const matches=key=>prefixes.some(value=>key===value||(/[.:]$/.test(value)&&key.startsWith(value)));
    const keys=()=>Array.from({length:store.length},(_,i)=>store.key(i)).filter(key=>key&&matches(key));
    const metadata=()=>{const raw=store.getItem(metaKey);if(!raw)return {};const value=JSON.parse(raw);if(!value||Array.isArray(value)||typeof value!=='object')throw new Error('Draft retention data is damaged.');return value;};
    function prune(){const times=metadata(),now=Date.now();let changed=false;for(const key of keys()){if(!Number.isFinite(times[key])){times[key]=now;changed=true;}else if(times[key]<now-ttl){store.removeItem(key);delete times[key];changed=true;}}if(changed)store.setItem(metaKey,JSON.stringify(times));return times;}
    cleanup.add(()=>{keys().forEach(key=>store.removeItem(key));store.removeItem(metaKey);});
    return {
      getItem(key){if(!matches(key))throw new Error('Draft key outside account scope.');try{prune();}catch(_){}return store.getItem(key);},
      setItem(key,raw){if(!active||!matches(key))throw new Error('Draft account is unavailable.');raw=String(raw);const times=prune(),others=keys().filter(value=>value!==key);if(raw.length*2>maxRecord||others.length>=maxRecords||others.reduce((size,key)=>size+(store.getItem(key)?.length||0)*2,0)+raw.length*2>maxTotal)throw new Error('Draft storage is full; existing copies were kept.');store.setItem(key,raw);times[key]=Date.now();store.setItem(metaKey,JSON.stringify(times));},
      removeItem(key){if(matches(key)){store.removeItem(key);const times=metadata();delete times[key];store.setItem(metaKey,JSON.stringify(times));}}
    };
  }
  window.WidgetDeckDrafts = {create, bindForm, storage, onLogout(callback) {cleanup.add(callback); return ()=>cleanup.delete(callback);}, limits:{ttl,maxRecord,maxTotal,maxRecords}};
  document.querySelectorAll('form[data-draft-form]:not([data-draft-custom])').forEach(form=>bindForm(form));
})();
