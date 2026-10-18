(() => {
  const dirtyForms=new Set();
  window.workspaceCanLeave=()=>!dirtyForms.size||confirm('Discard unsaved changes to this workspace?');
  document.querySelectorAll('.campaign-tool:not(.kanban-page) form,dialog.campaign-dialog:not(#new-deck-dialog) form').forEach(form=>{
    const state=document.createElement('p');state.className='workspace-save-status';state.setAttribute('role','status');state.setAttribute('aria-live','polite');state.textContent=form.classList.contains('character-card')||form.querySelector('[name=reference_notes]')?'All changes saved':'Ready';form.append(state);
    form.addEventListener('input',()=>{dirtyForms.add(form);state.textContent='Unsaved changes';});
    form.addEventListener('submit',()=>{dirtyForms.delete(form);state.textContent='Saving…';});
    form.closest('dialog')?.addEventListener('close',()=>{dirtyForms.delete(form);});
  });
  window.addEventListener('beforeunload',event=>{if(dirtyForms.size){event.preventDefault();event.returnValue='';}});
  const params=new URLSearchParams(location.search),owner=document.body.dataset.owner||'',key='dashboard.workspace.last.v1.'+owner;
  let saved={};try{saved=JSON.parse(localStorage.getItem(key)||'{}');}catch(_){}
  const remember=(kind,value)=>{saved[kind]=value;try{localStorage.setItem(key,JSON.stringify(saved));}catch(_){}};
  const main=document.querySelector('main.campaign-tool,main.flashcard-page');
  let select=main?.querySelector('#board-select,.campaign-select select,#flashcard-deck');
  if(main&&select){
    const name=select.id==='board-select'?'Boards':select.id==='flashcard-deck'?'Decks':location.pathname.includes('frostgrave')?'Warbands':'Trackers';
    const wrapper=document.createElement('div');wrapper.className='workspace-split';const aside=document.createElement('aside');aside.className='workspace-library';aside.setAttribute('aria-label',name);
    const title=document.createElement('h2');title.textContent=name;const search=document.createElement('input');search.type='search';search.placeholder='Find '+name.toLowerCase();search.setAttribute('aria-label',search.placeholder);const list=document.createElement('div');list.className='workspace-library-list';aside.append(title,search,list);
    const content=document.createElement('div');content.className='workspace-content';let heading=main.querySelector('.tool-heading');if(!heading&&main.matches('.flashcard-page')){heading=document.createElement('div');heading.className='tool-heading';const text=document.createElement('div');main.querySelectorAll(':scope>.eyebrow,:scope>h1,:scope>.lead').forEach(node=>text.append(node));const create=document.createElement('button');create.type='button';create.className='primary';create.textContent='+ New deck';create.addEventListener('click',()=>{wrapper.classList.remove('mobile-browsing');wrapper.classList.add('mobile-editing');document.querySelector('#new-deck-name').focus();});heading.append(text,create);main.prepend(heading);}const children=[...main.children].filter(child=>child!==heading);children.forEach(child=>content.append(child));wrapper.append(aside,content);main.append(wrapper);
    if(main.matches('.campaign-tool:not(.kanban-page)')){let previous=select.value;select.removeAttribute('onchange');select.addEventListener('change',()=>{if(!window.workspaceCanLeave()){select.value=previous;return;}dirtyForms.clear();previous=select.value;location.assign(select.value);});}
    const original=select.closest('label')||select;original.classList.add('workspace-library-original');
    const back=document.createElement('button');back.type='button';back.className='workspace-back workspace-mobile-back';back.textContent='← '+name;content.prepend(back);
    let browsingRequested=false;
    window.addEventListener('popstate',()=>{browsingRequested=false;});
    document.addEventListener('submit',event=>{if(event.target.id==='new-flashcard-deck')browsingRequested=false;});
    content.tabIndex=-1;
    const showEditor=()=>{wrapper.classList.add('mobile-editing');wrapper.classList.remove('mobile-browsing');if(innerWidth<=720)requestAnimationFrame(()=>{const field=content.querySelector('textarea:not(:disabled),input:not(:disabled):not([type=hidden])');(field||content).focus({preventScroll:true});});};
    window.addEventListener('workspace:selected',()=>{if(!browsingRequested)showEditor();});
    const showLibrary=()=>{browsingRequested=true;wrapper.classList.remove('mobile-editing');wrapper.classList.add('mobile-browsing');search.focus();};
    back.addEventListener('click',showLibrary);window.addEventListener('workspace:browse',showLibrary);
    function render(){
      list.replaceChildren();[...select.options].filter(o=>o.value).forEach(option=>{const button=document.createElement('button');button.type='button';button.disabled=select.disabled;button.textContent=option.textContent;button.setAttribute('aria-pressed',String(option.value===select.value));button.hidden=!option.textContent.toLowerCase().includes(search.value.toLowerCase());button.addEventListener('click',()=>{if(select.disabled)return;select.value=option.value;select.dispatchEvent(new Event('change',{bubbles:true}));if(select.value===option.value){browsingRequested=false;remember(location.pathname,option.value);showEditor();}render();});list.append(button);});
      if(!list.childElementCount){const p=document.createElement('p');p.className='hint';p.textContent='Create your first '+name.toLowerCase().replace(/s$/,'')+' to get started.';list.append(p);}
    }
    render();search.addEventListener('input',render);new MutationObserver(render).observe(select,{childList:true,attributes:true,attributeFilter:['disabled']});select.addEventListener('change',render);
    if(!location.search&&saved[location.pathname]&&[...select.options].some(o=>o.value===saved[location.pathname])){select.value=saved[location.pathname];select.dispatchEvent(new Event('change',{bubbles:true}));showEditor();}
    if(params.get('new')==='1'||params.has('board')||params.has('party')||params.has('table')||params.has('deck'))showEditor();
    else if(innerWidth<=720)wrapper.classList.add('mobile-browsing');
  }
  document.querySelectorAll('[data-workspace-dialog]').forEach(button=>button.addEventListener('click',()=>{const dialog=document.getElementById(button.dataset.workspaceDialog);dialog.showModal();dialog.querySelector('input')?.focus();}));
  document.querySelectorAll('[data-workspace-close]').forEach(button=>button.addEventListener('click',()=>button.closest('dialog').close()));
  const dialog=document.querySelector('dialog.campaign-dialog');if(params.get('new')==='1'&&dialog){dialog.showModal();dialog.querySelector('input')?.focus();}
  const special=[['#zk-editor','#zk-workspace','#zk-library','Zettels'],['#rack-detail','#rack-workspace',null,'Paints']];
  special.forEach(([editorSelector,workspaceSelector,librarySelector,label])=>{
    const editor=document.querySelector(editorSelector),workspace=document.querySelector(workspaceSelector);if(!editor||!workspace)return;
    const back=document.createElement('button');back.type='button';back.className='workspace-back workspace-mobile-back';back.textContent='← '+label;editor.prepend(back);
    back.addEventListener('click',()=>{workspace.classList.remove('mobile-editing');workspace.classList.add('mobile-browsing');document.querySelector(label==='Zettels'?'#zk-search':'#rack-search')?.focus();});
    window.addEventListener('workspace:selected',()=>{workspace.classList.remove('mobile-browsing');workspace.classList.add('mobile-editing');});
    if(innerWidth<=720)workspace.classList.add('mobile-browsing');
  });
  document.querySelectorAll('.tool-heading>a[download]').forEach(link=>{const more=document.createElement('details');more.className='workspace-more';const summary=document.createElement('summary');summary.textContent='More';const menu=document.createElement('div');link.replaceWith(more);menu.append(link);more.append(summary,menu);});
})();

// Native disclosure controls retain tab order and work in dynamically mounted workspaces.
document.addEventListener('keydown',event=>{
  if(event.key!=='Escape')return;
  const menu=event.target.closest('details.workspace-more[open]');
  if(menu){event.preventDefault();menu.open=false;menu.querySelector('summary').focus();}
});
document.addEventListener('click',event=>{
  const own=event.target.closest('details.workspace-more');
  document.querySelectorAll('details.workspace-more[open]').forEach(menu=>{if(menu!==own)menu.open=false;});
  const action=event.target.closest('button,a');
  if(own&&action){own.open=false;queueMicrotask(()=>{if(document.activeElement===action)own.querySelector('summary').focus();});}
});
