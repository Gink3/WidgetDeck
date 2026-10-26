(() => {
  const cards=document.querySelector('.cards'),status=document.querySelector('#widget-reorder-status');if(!cards||!status)return;
  const groups=JSON.parse(document.querySelector('#utility-categories').textContent),links=groups.flatMap(g=>g.links),widgets=()=>[...cards.querySelectorAll('.utility-tile')];
  const storageKey='dashboard.home.widget-order.v1';
  try{const saved=JSON.parse(localStorage.getItem(storageKey)||'[]'),byId=new Map(widgets().map(w=>[w.dataset.tileId,w]));saved.forEach(id=>{if(byId.has(id)){cards.append(byId.get(id));byId.delete(id);}});byId.forEach(w=>cards.append(w));}catch(_){}
  function groupCards(){cards.querySelectorAll('.utility-category-heading').forEach(h=>h.remove());groups.forEach(group=>{const members=widgets().filter(w=>w.dataset.category===group.name);const h=document.createElement('h2');h.className='utility-category-heading';h.textContent=group.name;h.dataset.category=group.name;cards.append(h,...members);});}
  function filter(){const words=document.querySelector('#utility-search').value.toLowerCase().trim().split(/\s+/),category=document.querySelector('#utility-category').value;let count=0;
    widgets().forEach(w=>{w.hidden=Boolean(category&&category!==w.dataset.category)||!words.every(word=>(w.textContent+' '+w.dataset.category).toLowerCase().includes(word));if(!w.hidden)count++;});
    cards.querySelectorAll('.utility-category-heading').forEach(h=>{h.hidden=!widgets().some(w=>!w.hidden&&w.dataset.category===h.dataset.category);});document.querySelector('#utility-results').textContent=count?'':'No utilities found. Try another search or category.';
  }
  groupCards();filter();document.querySelector('#utility-search').addEventListener('input',filter);document.querySelector('#utility-category').addEventListener('change',filter);
  let dragging=null;
  widgets().forEach(w=>{w.draggable=true;w.addEventListener('dragstart',e=>{if(e.target.closest('button')){e.preventDefault();return;}dragging=w;e.dataTransfer.setData('text/plain',w.dataset.tileId);w.classList.add('is-dragging');});w.addEventListener('dragend',()=>{w.classList.remove('is-dragging');dragging=null;groupCards();filter();try{localStorage.setItem(storageKey,JSON.stringify(widgets().map(x=>x.dataset.tileId)));}catch(_){}status.textContent='Utility order saved.';});});
  cards.addEventListener('dragover',e=>{if(!dragging)return;const target=e.target.closest('.utility-tile');if(!target||target===dragging||target.dataset.category!==dragging.dataset.category)return;e.preventDefault();const b=target.getBoundingClientRect();cards.insertBefore(dragging,e.clientY>b.top+b.height/2?target.nextSibling:target);});cards.addEventListener('drop',e=>e.preventDefault());
  const makeLink=(label,url,context,external=false)=>{const a=document.createElement('a');a.className='launcher-shortcut';a.href=url;const strong=document.createElement('strong');strong.textContent=label;const small=document.createElement('small');small.textContent=context;a.append(strong,small);if(external){a.target='_blank';a.rel='noopener noreferrer';}return a;};
  function favourites(ids,targets=[]){const box=document.querySelector('#launcher-favourites');box.replaceChildren();links.filter(l=>ids.includes(l.id)).forEach(l=>box.append(makeLink(l.label,l.url,l.category,l.external)));targets.forEach(item=>{const row=document.createElement('div');row.className='launcher-favourite-target';const remove=document.createElement('button');remove.type='button';remove.textContent='★';remove.setAttribute('aria-label','Unpin '+item.label);remove.addEventListener('click',async()=>{remove.disabled=true;try{await window.pinLauncherTarget(item,false);}catch(error){document.querySelector('#launcher-status').textContent=error.message;remove.disabled=false;}});row.append(makeLink(item.label,item.url,item.utility_label+' · '+(item.context||'Saved item'),item.external),remove);box.append(row);});document.querySelectorAll('[data-pin]').forEach(button=>{const pinned=ids.includes(button.dataset.pin);button.setAttribute('aria-pressed',String(pinned));button.textContent=pinned?'★':'☆';button.setAttribute('aria-label',`${pinned?'Unpin':'Pin'} ${links.find(l=>l.id===button.dataset.pin).label}`);});}
  window.launcherState().then(state=>{favourites(state.favourites,state.favourite_destinations);const recent=document.querySelector('#launcher-recent');
    function recentItems(){if(!state.recent.length)return;recent.replaceChildren(...state.recent.map(item=>{
      const row=document.createElement('div');row.className='launcher-favourite-target';
      const pinned=(state.favourite_destinations||[]).some(target=>target.utility===item.utility&&String(target.id)===String(item.id)&&(target.kind||'')===(item.kind||''));
      const pin=document.createElement('button');pin.type='button';pin.textContent=pinned?'★':'☆';pin.setAttribute('aria-label',`${pinned?'Unpin':'Pin'} ${item.label}`);pin.setAttribute('aria-pressed',String(pinned));
      pin.addEventListener('click',async()=>{pin.disabled=true;try{await window.pinLauncherTarget(item,!pinned);}catch(error){document.querySelector('#launcher-status').textContent=error.message;pin.disabled=false;}});
      row.append(makeLink(item.label,item.url,`${item.utility_label}${item.context?' · '+item.context:''}`),pin);return row;
    }));}
    recentItems();window.addEventListener('launcher:favourites',()=>{favourites(state.favourites,state.favourite_destinations);recentItems();});
    document.querySelectorAll('[data-pin]').forEach(button=>button.addEventListener('click',async()=>{const id=button.dataset.pin,pinned=!state.favourites.includes(id);button.disabled=true;try{const r=await fetch('/api/launcher/favourites/'+encodeURIComponent(id),{method:'PUT',headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf_token},body:JSON.stringify({pinned})});if(!r.ok)throw new Error('Unable to update favourites.');state.favourites=pinned?[...state.favourites,id]:state.favourites.filter(x=>x!==id);favourites(state.favourites,state.favourite_destinations);}catch(error){document.querySelector('#launcher-status').textContent=error.message;}finally{button.disabled=false;}}));
  }).catch(error=>{document.querySelector('#launcher-status').textContent=error.message;});
})();

(() => {
  const container = document.querySelector('#home-recent-activity');
  if (!container) return;

  const formatTime = (value) => new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  const activityItem = (entry) => {
    const item = document.createElement('article');
    item.className = 'activity-item';
    const title = document.createElement('strong');
    title.textContent = entry.resource_name;
    const meta = document.createElement('div');
    meta.className = 'activity-meta';
    const added = document.createElement('span');
    added.className = 'activity-added';
    added.textContent = `+${entry.added_lines}`;
    const removed = document.createElement('span');
    removed.className = 'activity-removed';
    removed.textContent = `−${entry.removed_lines}`;
    if (entry.count_unit !== 'words' && entry.added_lines) meta.append(added);
    if (entry.count_unit !== 'words' && entry.removed_lines) meta.append(removed);
    const unit = document.createElement('span');
    unit.className = 'activity-unit';
    unit.textContent = entry.count_unit === 'words' ? 'Edited' : 'lines';
    meta.append(unit);
    meta.title = entry.count_unit === 'words' ? 'Earlier edit; line totals were not recorded.' : `${entry.added_lines} lines added, ${entry.removed_lines} removed`;
    if (!['lines', 'words'].includes(entry.count_unit)) {
      meta.replaceChildren();
      unit.textContent = `${entry.action} ${entry.added_lines} ${entry.count_unit}`;
      meta.append(unit);
      meta.title = unit.textContent;
    }
    const time = document.createElement('time');
    time.dateTime = entry.occurred_at;
    time.textContent = formatTime(entry.occurred_at);
    item.append(title, meta, time);
    return item;
  };

  fetch('/api/activity')
    .then((response) => response.ok ? response.json() : Promise.reject())
    .then(({ activity }) => {
      container.replaceChildren();
      if (!activity.length) {
        container.innerHTML = '<p class="muted">Your activity in Dashboard will appear here.</p>';
        return;
      }
      activity.forEach((entry) => container.append(activityItem(entry)));
    })
    .catch(() => { container.innerHTML = '<p class="muted">Recent activity is unavailable right now.</p>'; });
})();
