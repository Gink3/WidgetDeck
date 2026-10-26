(() => {
  let statePromise;
  window.launcherState=()=>statePromise||(statePromise=fetch('/api/launcher').then(r=>{if(!r.ok)throw new Error('Launcher is unavailable.');return r.json();}));
  window.recordLauncherVisit=async(utility,id,kind='')=>{
    queueMicrotask(()=>window.setLauncherDestination?.(utility,id,kind));
    try{const state=await window.launcherState();await fetch('/api/launcher/recent',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf_token},body:JSON.stringify({utility,id:String(id),kind})});}catch(_){} // Navigation works if history is unavailable.
  };
  window.launcherLast=async utility=>{if(location.search||location.hash)return null;try{const r=await fetch('/api/launcher/recent?utility='+encodeURIComponent(utility));return (await r.json()).last[0]||null;}catch(_){return null;}};
  const wiki=document.querySelector('#wiki-root[data-page="editor"]');
  if(wiki&&wiki.dataset.pageSlug!=='new')fetch('/tools/wiki/api/pages/'+encodeURIComponent(wiki.dataset.pageSlug)).then(r=>r.ok?r.json():null).then(data=>{if(data?.page)window.recordLauncherVisit('wiki',data.page.id);}).catch(()=>{});
  document.querySelectorAll('[data-launcher-utility][data-launcher-id]').forEach(node=>{if(node.dataset.launcherId)window.recordLauncherVisit(node.dataset.launcherUtility,node.dataset.launcherId);});
  const board=document.querySelector('.kanban-board[data-board]');if(board)window.recordLauncherVisit('kanban',board.dataset.board);
})();

(() => {
  window.pinLauncherTarget=async(target,pinned)=>{
    const state=await window.launcherState();
    const response=await fetch('/api/launcher/favourite-targets',{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf_token},body:JSON.stringify({...target,pinned})});
    const data=await response.json();if(!response.ok)throw new Error(data.error||'Unable to update favourites.');
    state.favourite_destinations=data.favourite_destinations;window.dispatchEvent(new Event('launcher:favourites'));return data;
  };
  // Retained for widgets that announce their current destination. Pin controls
  // live in the launcher so every widget shares the same global navigation.
  window.setLauncherDestination=(utility,id,kind='')=>{
    window.launcherDestination=id?{utility,id:String(id),kind}:null;
  };
})();
