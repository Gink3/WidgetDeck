(() => {
  const dialog=document.querySelector('#global-search-dialog');if(!dialog)return;
  const input=document.querySelector('#global-search-input'),home=document.querySelector('#utility-search');
  function connect(field,box,prefix){
    let timer,sequence=0,controller,active=-1,options=[];
    field.maxLength=160;field.setAttribute('role','combobox');field.setAttribute('aria-autocomplete','list');field.setAttribute('aria-expanded','false');field.setAttribute('aria-controls',prefix+'-list');
    function message(text,error=false){box.replaceChildren();const p=document.createElement('p');p.className='search-status'+(error?' search-error':'');p.setAttribute('role','status');p.textContent=text;box.append(p);}
    function select(index){active=index;options.forEach((option,i)=>option.setAttribute('aria-selected',String(i===active)));if(options[active]){field.setAttribute('aria-activedescendant',options[active].id);options[active].scrollIntoView({block:'nearest'});}else field.removeAttribute('aria-activedescendant');}
    async function run(){
      const request=++sequence;controller?.abort();options=[];active=-1;field.removeAttribute('aria-activedescendant');
      const query=field.value.trim();if(!query){box.hidden=field===home;field.setAttribute('aria-expanded','false');message('Search utilities, actions and enabled widget content.');return;}
      box.hidden=false;field.setAttribute('aria-expanded','true');message('Searching…');controller=new AbortController();
      try{
        const response=await fetch('/api/search?'+new URLSearchParams({q:query}),{signal:controller.signal});const data=await response.json();if(request!==sequence)return;if(!response.ok)throw new Error(data.error||'Search is unavailable.');
        box.replaceChildren();const list=document.createElement('ul');list.id=prefix+'-list';list.setAttribute('role','listbox');list.setAttribute('aria-label','Search results');box.append(list);
        for(const [kind,label] of [['utility','Utilities'],['action','Actions'],['content','Content']]){
          const results=data.results.filter(result=>result.result_kind===kind);if(!results.length)continue;
          const heading=document.createElement('li');heading.setAttribute('role','presentation');const h=document.createElement('h3');h.textContent=label;heading.append(h);list.append(heading);
          results.forEach(result=>{const li=document.createElement('li');li.setAttribute('role','presentation');const a=document.createElement('a');a.href=result.url;a.id=prefix+'-'+options.length;a.setAttribute('role','option');a.setAttribute('aria-selected','false');a.dataset.kind=kind;a.dataset.utility=result.utility;
            const title=document.createElement('strong');title.textContent=result.label;const context=document.createElement('small');context.textContent=result.utility_label+(result.context?' · '+result.context:'');a.append(title,context);
            if(result.preview){const preview=document.createElement('span');preview.className='search-preview';preview.textContent=result.preview;a.append(preview);}
            if(result.external){a.target='_blank';a.rel='noopener noreferrer';}li.append(a);list.append(li);options.push(a);
          });
        }
        const p=document.createElement('p');p.className='search-status';p.setAttribute('role','status');p.textContent=data.results.length?`${data.results.length} ${data.results.length===1?'result':'results'}${data.has_more?' · More matches available; narrow your search.':''}`:'No results. Try a reference number, name or another phrase.';
        if(data.unavailable.length)p.textContent+=' Some sources are temporarily unavailable.';box.append(p);select(options.length?0:-1);
      }catch(error){if(request===sequence&&error.name!=='AbortError')message(error.message,true);}
    }
    field.addEventListener('input',()=>{clearTimeout(timer);++sequence;controller?.abort();options=[];active=-1;field.removeAttribute('aria-activedescendant');if(field.value.trim()){box.hidden=false;message('Searching…');}timer=setTimeout(run,200);});
    field.addEventListener('keydown',event=>{
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();if(options.length)select((active+(event.key==='ArrowDown'?1:-1)+options.length)%options.length);}
      else if(event.key==='Enter'&&options[active]){event.preventDefault();options[active].click();}
      else if(event.key==='Escape'){if(field===home){event.preventDefault();field.value='';field.dispatchEvent(new Event('input',{bubbles:true}));box.hidden=true;}else dialog.close();}
    });
    return ()=>{clearTimeout(timer);run();};
  }
  const hint=document.querySelector('#global-search-open kbd');if(hint)hint.textContent=/Mac|iPhone|iPad/.test(navigator.platform)?'⌘K':'Ctrl K';
  const refresh=connect(input,document.querySelector('#global-search-results'),'global');
  if(home){connect(home,document.querySelector('#home-search-results'),'home');}
  document.querySelector('#global-search-open').addEventListener('click',()=>{dialog.showModal();input.focus();refresh();});
  document.querySelector('#global-search-close').addEventListener('click',()=>dialog.close());
  window.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='k'){event.preventDefault();event.stopImmediatePropagation();if(!dialog.open)dialog.showModal();input.focus();refresh();}},true);
})();
