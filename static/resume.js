/* Foreground reads are coalesced; applying them requires an unchanged clean editor. */
(() => {
  'use strict';
  const runtime=window.WidgetDeckRuntime;
  if(!runtime)return;
  const registrations=new Map();
  function registerResume({id,title='Saved data',host,load,apply,isDirty,identity=()=>'',version=()=>'',minAge=30000}) {
    if(!/^[a-z0-9-]+$/.test(id) || !host || typeof load!=='function' || typeof apply!=='function' || typeof isDirty!=='function')throw new Error('Invalid foreground refresh registration.');
    registrations.get(id)?.dispose();
    const panel=document.createElement('aside');panel.className='resume-refresh';panel.hidden=true;
    const message=document.createElement('p');message.setAttribute('role','status');message.setAttribute('aria-live','polite');
    const button=document.createElement('button');button.type='button';button.textContent='Refresh saved data';
    panel.append(message,button);host.append(panel);
    let disposed=false,pending=null,controller=null,generation=0,lastFetched=Date.now(),stale=false;
    const notify=text=>{if(disposed)return;panel.hidden=false;message.textContent=title+': '+text;};
    const clean=()=>runtime.state.verified && runtime.state.session==='active' && !document.body.dataset.accountMismatch && !document.hidden;
    async function refresh(force=false) {
      if(disposed || !clean())return;
      if(pending && !controller?.signal.aborted)return pending;
      if(!force && !stale && Date.now()-lastFetched<minAge)return;
      stale=true;
      if(runtime.state.saving || isDirty()) {notify('Keep your unsaved edits. Save or copy them before refreshing.');return;}
      const selected=JSON.stringify(identity()),baseline=JSON.stringify(version()),current=++generation;
      controller=new AbortController();const signal=controller.signal;
      button.disabled=true;
      const work=Promise.resolve().then(async()=>{
        try {
          const data=await load({signal});
          if(disposed || signal.aborted || current!==generation || !clean())return;
          if(runtime.state.saving || isDirty() || selected!==JSON.stringify(identity()) || baseline!==JSON.stringify(version())) {
            notify('Newer edits or navigation were kept. Refresh after saving or copying your work.');return;
          }
          apply(data);
          lastFetched=Date.now();stale=false;panel.hidden=true;
        } catch(error) {
          if(!disposed && current===generation && !signal.aborted)notify('Could not refresh. Your current work is unchanged; retry when connected.');
        } finally {
          if(current===generation){pending=null;button.disabled=false;}
        }
      });
      pending=work;return work;
    }
    button.addEventListener('click',async()=>{
      const before=generation;
      await runtime.checkSession();
      // The verified resume event may already have started or completed this
      // refresh, including a synchronous page-reload callback.
      if(generation!==before)return pending;
      await refresh(true);
    });
    const registration={refresh,
      fresh(){registration.cancel();lastFetched=Date.now();stale=false;panel.hidden=true;},
      cancel(){generation++;controller?.abort();pending=null;stale=true;button.disabled=false;},
      dispose(){disposed=true;registration.cancel();panel.remove();if(registrations.get(id)===registration)registrations.delete(id);}
    };
    registrations.set(id,registration);return registration;
  }
  window.addEventListener('widgetdeck:resume',event=>registrations.forEach(registration=>registration.refresh(event.detail?.recovered===true)));
  for(const type of ['widgetdeck:session-expired','widgetdeck:account-changed'])window.addEventListener(type,()=>registrations.forEach(registration=>registration.cancel()));
  runtime.registerResume=registerResume;
})();
