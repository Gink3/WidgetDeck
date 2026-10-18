(() => {
  'use strict';
  const board = document.querySelector('.kanban-board');
  if (!board) return;
  const $ = (selector) => document.querySelector(selector);
  const detail = $('#kanban-detail'), form = $('#item-edit-form');
  const title = $('#item-title'), notes = $('#item-notes'), column = $('#item-column');
  const transferForm = $('#item-transfer-form'), transferBoard = $('#transfer-board'), transferColumn = $('#transfer-column'), transferButton = $('#transfer-item');
  let destinationRequest = 0;
  let columnMode = false, draggedColumn = null;
  const columnSections = () => [...board.querySelectorAll('.kanban-column')];
  $('#manage-columns').addEventListener('click', () => {
    if (!canLeave()) return;
    dirty = false; $('#comment-body').value = '';
    $('#column-manager').showModal();
  });
  async function changeColumns(event, removing) {
    event.preventDefault();
    const payload = { expected_order: columnOrder() };
    if (removing) payload.destination_id = Number($('#column-destination').value) || null;
    else payload.name = $('#column-name').value;
    try {
      const suffix = removing ? `/${$('#remove-column').value}` : '';
      const response = await fetch(`/api/tools/kanban/boards/${board.dataset.board}/columns${suffix}`, {
        method: removing ? 'DELETE' : 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to change columns.');
      location.reload();
    } catch (error) { $('#column-manager-status').textContent = error.message; }
  }
  $('#add-column-form').addEventListener('submit', e => changeColumns(e, false));
  $('#remove-column-form').addEventListener('submit', e => changeColumns(e, true));
  const columnOrder = () => columnSections().map((section) => Number(section.dataset.column));
  const search = $('#kanban-search');
  let commentSaving = false;
  let selected = null, dirty = false, saving = false, moving = false, requestNumber = 0, dragged = null, ignoreClickUntil = 0;
  const date = (value) => new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
  const announce = (message, error = false) => { $('#kanban-status').textContent = message; $('#kanban-status').classList.toggle('error', error); };
  const detailStatus = (message, error = false) => { $('#detail-status').textContent = message; $('#detail-status').classList.toggle('error', error); };
  async function api(id, options = {}, suffix = '') {
    const response = await fetch(`/api/tools/kanban/items/${id}${suffix}`, { ...options, headers: { 'Content-Type': 'application/json' } });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || 'Unable to save. Please try again.');
    return data.item;
  }
  const cardFor = (id) => board.querySelector(`[data-item="${id}"]`);
  const zoneFor = (id) => board.querySelector(`[data-column="${id}"] .kanban-dropzone`);
  const cardsIn = (zone) => [...zone.querySelectorAll('.kanban-card')];
  function updateCounts() {
    const query = search.value.trim().toLocaleLowerCase();
    let matches = 0, total = 0;
    board.querySelectorAll('.kanban-card').forEach((card) => {
      const match = /^#\d+$/.test(query) ? Number(query.slice(1)) === Number(card.dataset.item)
        : card.querySelector('.kanban-card-title').textContent.toLocaleLowerCase().includes(query);
      card.hidden = !match; matches += Number(match); total++;
    });
    $('#clear-kanban-search').disabled = !query;
    $('#kanban-search-count').textContent = query ? `${matches} of ${total} items · clear search to reorder cards` : '';
    columnSections().forEach((section, index, all) => {
      section.draggable = columnMode && !moving;
      section.querySelector('.column-order-controls').hidden = !columnMode;
      section.querySelector('[data-column-step="-1"]').disabled = moving || index === 0;
      section.querySelector('[data-column-step="1"]').disabled = moving || index === all.length - 1;
    });
    board.querySelectorAll('.kanban-column').forEach((col) => {
      const cards = cardsIn(col);
      const visible = cards.filter((card) => !card.hidden).length;
      col.querySelector('.column-count').textContent = query ? `${visible} / ${cards.length}` : cards.length;
      col.querySelector('.kanban-dropzone').classList.toggle('is-empty', visible === 0);
      cards.forEach((card, index) => {
        card.querySelector('[data-reorder="up"]').disabled = Boolean(query) || moving || index === 0;
        card.querySelector('[data-reorder="down"]').disabled = Boolean(query) || moving || index === cards.length - 1;
        card.draggable = !query && !columnMode && !moving && !saving;
      });
    });
  }
  function updateCard(item) {
    const card = cardFor(item.id);
    card.classList.toggle('is-cancelled', Boolean(item.cancelled_at));
    card.querySelector('.cancelled-badge').hidden = !item.cancelled_at;
    card.dataset.revision = item.revision;
    card.querySelector('.kanban-card-title').textContent = item.title;
    card.querySelector('.kanban-card-notes').textContent = item.notes;
    card.querySelector('.kanban-card-notes').hidden = !item.notes;
    const zone = zoneFor(item.column_id);
    if (card.parentElement !== zone) zone.append(card);
    updateCounts();
  }
  function renderHistory(item) {
    const list = $('#item-history'); list.replaceChildren();
    const events = [...item.history];
    if (!events.some((entry) => entry.action === 'created')) events.push({ action: 'created', occurred_at: item.created_at, changes: {} });
    events.forEach((entry) => {
      const li = document.createElement('li'), heading = document.createElement('strong'), time = document.createElement('time');
      const actions = { created: 'Item created', updated: 'Item updated', moved: 'Status changed', reordered: 'Order changed', transferred: 'Board changed', cancelled: 'Item cancelled', restored: 'Item restored' };
      heading.textContent = `${actions[entry.action] || 'Item updated'}${entry.actor ? ` · ${entry.actor}` : ''}`;
      time.dateTime = entry.occurred_at; time.textContent = date(entry.occurred_at); li.append(heading, time);
      Object.entries(entry.changes).forEach(([field, change]) => {
        const details = document.createElement('details'), summary = document.createElement('summary'), values = document.createElement('div');
        summary.textContent = `${field[0].toUpperCase() + field.slice(1)} changed`;
        values.className = 'history-values';
        [['Before', change.before], ['After', change.after]].forEach(([label, value]) => {
          const strong = document.createElement('strong'), p = document.createElement('p');
          strong.textContent = label; p.textContent = String(value?.name ?? value ?? '(empty)'); values.append(strong, p);
        });
        details.append(summary, values); li.append(details);
      });
      list.append(li);
    });
  }
  function fillDetail(item) {
    window.recordLauncherVisit?.('kanban',item.id,'item');
    selected = item; dirty = false;
    title.value = item.title; notes.value = item.notes; column.value = item.column_id;
    $('#detail-key').textContent = `ITEM #${item.id}`;
    $('#item-created').textContent = date(item.created_at); $('#item-updated').textContent = date(item.updated_at || item.created_at);
    $('#item-save-state').textContent = 'All changes saved'; $('#save-item').disabled = true;
    form.hidden = false; $('#item-history-section').hidden = false;
    transferForm.hidden = false;
    $('#item-actions').hidden = false; $('#cancel-item').textContent = item.cancelled_at ? 'Restore item' : 'Cancel item';
    renderHistory(item); renderComments(item); renderLinks(item);
  }
  function renderLinks(item) {
    $('#item-links-section').hidden = false;
    [['#item-links',item.links || [],false],['#item-dependents',item.dependents || [],true]].forEach(([selector,links,reverse]) => {
      const list = $(selector); list.replaceChildren();
      links.forEach(link => {
        const li = document.createElement('li'), a = document.createElement('a');
        a.href = `/tools/kanban?board=${link.board_id}&item=${link.target_id}`;
        a.textContent = `${link.kind === 'depends_on' ? (reverse ? 'Required by' : 'Depends on') : 'Related'} #${link.target_id} · ${link.title} · ${link.cancelled_at ? 'Cancelled' : link.column_name}`;
        a.addEventListener('click',event => { if (!canLeave()) event.preventDefault(); }); li.append(a);
        if (!reverse) {
          const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Remove link';
          button.addEventListener('click',() => saveLinks((selected.links || []).filter(l => l.target_id !== link.target_id || l.kind !== link.kind)));
          li.append(button);
        }
        list.append(li);
      });
    });
  }
  async function saveLinks(links) {
    if (!selected || dirty || saving || moving) { detailStatus('Save your item edits before changing links.',true); return; }
    saving = true;
    try {
      const item = await api(selected.id,{method:'PUT',body:JSON.stringify({links,revision:selected.revision})},'/links');
      fillDetail(item); updateCard(item); detailStatus('Links saved.');
    } catch(error) { detailStatus(error.message,true); }
    finally { saving = false; }
  }
  $('#item-link-form').addEventListener('submit',event => {
    event.preventDefault();
    saveLinks([...(selected?.links || []).map(l => ({target_id:l.target_id,kind:l.kind})),{target_id:Number($('#link-target').value),kind:$('#link-kind').value}]);
  });
  function renderComments(item) {
    $('#item-comments-section').hidden = false;
    const list = $('#item-comments'); list.replaceChildren();
    (item.comments || []).forEach(comment => {
      const li = document.createElement('li'), heading = document.createElement('strong'), body = document.createElement('p');
      heading.textContent = `${comment.author || 'Account'} · ${date(comment.created_at)}${comment.revision ? ' · edited' : ''}`;
      body.textContent = comment.body; li.append(heading, body);
      ['Edit', 'Delete'].forEach(action => {
        const button = document.createElement('button'); button.type = 'button'; button.textContent = action;
        button.addEventListener('click', async () => {
          const content = action === 'Edit' ? window.prompt('Edit comment', comment.body) : null;
          if (action === 'Edit' && content === null) return;
          if (action === 'Delete' && !window.confirm('Delete this comment permanently?')) return;
          button.disabled = true;
          const id = selected.id;
          try {
            const item = await api(id, { method: action === 'Delete' ? 'DELETE' : 'PATCH', body: JSON.stringify({body:content, revision:comment.revision}) }, `/comments/${comment.id}`);
            if (selected?.id === id) { selected.comments = item.comments; renderComments(item); detailStatus('Comment saved.'); }
          } catch(error) { detailStatus(error.message, true); button.disabled = false; }
        });
        li.append(button);
      });
      list.append(li);
    });
  }
  $('#item-comment-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!selected) return;
    const id = selected.id, text = $('#comment-body').value;
    $('#add-comment').disabled = true; commentSaving = true;
    try {
      const item = await api(id, {method:'POST', body:JSON.stringify({body:text})}, '/comments');
      if (selected?.id === id) { selected.comments = item.comments; renderComments(item); $('#comment-body').value = ''; detailStatus('Comment added.'); }
    } catch(error) { detailStatus(error.message, true); }
    finally { $('#add-comment').disabled = false; commentSaving = false; }
  });
  function canLeave() {
    if (saving || moving || commentSaving) { detailStatus('Please wait for the current change to finish saving.'); return false; }
    return (!dirty && !$('#comment-body').value.trim()) || window.confirm('Discard the unsaved changes to this item?');
  }
  function selectCard(id) {
    board.querySelectorAll('.kanban-card').forEach((card) => {
      const active = Number(card.dataset.item) === id;
      card.classList.toggle('selected', active); card.querySelector('.kanban-open').setAttribute('aria-expanded', String(active));
    });
  }
  function itemAddress(id){const url=new URL(location.href);url.searchParams.set('board',board.dataset.board);if(id)url.searchParams.set('item',id);else url.searchParams.delete('item');if(url.href!==location.href)history.pushState(null,'',url);}
  async function openItem(id) {
    if (!detail.hidden && selected?.id === id) { title.focus(); return; }
    if (!canLeave()) return;
    dirty = false; selected = null; $('#comment-body').value = '';
    const request = ++requestNumber;
    detail.hidden = false; $('.kanban-workspace').classList.add('detail-open');
    form.hidden = true; $('#item-history-section').hidden = true; selectCard(id);
    transferForm.hidden = true;
    $('#item-actions').hidden = true;
    $('#item-comments-section').hidden = true; $('#item-links-section').hidden = true;
    detailStatus('Loading item…'); $('#close-detail').focus();
    try {
      const item = await api(id);
      if (request !== requestNumber) return;
      fillDetail(item); updateCard(item); itemAddress(item.id); detailStatus(''); title.focus();
    } catch (error) { if (request === requestNumber) detailStatus(error.message, true); }
  }
  function closeDetail() {
    if (!canLeave()) return;
    const card = board.querySelector('.kanban-card.selected');
    ++requestNumber; selected = null; dirty = false; detail.hidden = true;
    $('.kanban-workspace').classList.remove('detail-open'); selectCard(null);itemAddress(null);window.setLauncherDestination?.('kanban',board.dataset.board); card?.querySelector('.kanban-open').focus();
  }
  $('#reorder-columns').addEventListener('click', () => {
    if (!canLeave()) return;
    closeDetail();
    columnMode = !columnMode;
    $('#reorder-columns').setAttribute('aria-pressed', String(columnMode));
    $('#reorder-columns').textContent = columnMode ? 'Finish reordering' : 'Reorder columns';
    const menu=$('.kanban-column-tools .workspace-more');
    if(columnMode)menu.before($('#reorder-columns'));else menu.querySelector('div').prepend($('#reorder-columns'));
    $('#reorder-columns').classList.toggle('primary',columnMode);
    $('#column-order-hint').hidden = !columnMode;
    board.classList.toggle('reordering-columns', columnMode); updateCounts();
  });
  async function moveColumn(section, before) {
    if (moving || saving || section === before || section.nextElementSibling === before) return;
    const original = columnSections(), expected = columnOrder();
    moving = true; board.insertBefore(section, before); updateCounts();
    try {
      const response = await fetch(`/api/tools/kanban/boards/${board.dataset.board}/columns/reorder`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column_ids: columnOrder(), expected_order: expected })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to reorder columns.');
      announce('Column order saved.');
    } catch (error) { original.forEach((entry) => board.append(entry)); announce(error.message, true); }
    finally { moving = false; updateCounts(); }
  }
  $('#close-detail').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (event) => {
    if (detail.hidden) return;
    if (event.key === 'Escape') { event.preventDefault(); closeDetail(); }
    if (event.key === 'Tab' && matchMedia('(max-width: 760px)').matches) {
      const focusable = [...detail.querySelectorAll('button, input, textarea, select, summary')].filter((el) => !el.disabled && el.getClientRects().length);
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  form.addEventListener('input', () => {
    if (!selected) return;
    dirty = title.value !== selected.title || notes.value !== selected.notes || Number(column.value) !== selected.column_id;
    $('#item-save-state').textContent = dirty ? 'Unsaved changes' : 'All changes saved'; $('#save-item').disabled = !dirty;
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault(); if (!selected || saving || moving || !dirty) return;
    saving = true; detailStatus('Saving…');
    [title, notes, column, $('#save-item')].forEach((el) => { el.disabled = true; }); updateCounts();
    try {
      const item = await api(selected.id, { method: 'PATCH', body: JSON.stringify({ title: title.value, notes: notes.value, column_id: Number(column.value), revision: selected.revision }) });
      updateCard(item); fillDetail(item); detailStatus('Changes saved.'); announce(`Saved “${item.title}”.`);
    } catch (error) { detailStatus(error.message, true); }
    finally { saving = false; [title, notes, column].forEach((el) => { el.disabled = false; }); $('#save-item').disabled = !dirty; updateCounts(); }
  });
  transferBoard.addEventListener('change', async () => {
    const request = ++destinationRequest;
    transferColumn.replaceChildren(new Option('Loading…', '')); transferColumn.disabled = true; transferButton.disabled = true;
    if (!transferBoard.value) { transferColumn.replaceChildren(new Option('Choose a board first', '')); return; }
    try {
      const response = await fetch(`/api/tools/kanban/boards/${transferBoard.value}`);
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Unable to load destination board.');
      if (request !== destinationRequest) return;
      transferColumn.replaceChildren(...data.board.columns.map((entry) => new Option(entry.name, entry.id)));
      transferColumn.disabled = data.board.columns.length === 0; transferButton.disabled = transferColumn.disabled;
      detailStatus('');
    } catch (error) { if (request === destinationRequest) detailStatus(error.message, true); }
  });
  transferForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!selected || saving || moving || transferColumn.disabled) return;
    if (dirty) { detailStatus('Save the item’s changes before moving it.', true); return; }
    moving = true; transferBoard.disabled = true; transferColumn.disabled = true; transferButton.disabled = true; updateCounts();
    [title, notes, column, $('#save-item')].forEach((el) => { el.disabled = true; });
    try {
      const item = await api(selected.id, { method: 'POST', body: JSON.stringify({ board_id: Number(transferBoard.value), column_id: Number(transferColumn.value), revision: selected.revision }) }, '/transfer');
      cardFor(item.id)?.remove();
      selected = null; dirty = false; ++requestNumber; detail.hidden = true; $('.kanban-workspace').classList.remove('detail-open');
      announce(`Moved “${item.title}” to ${transferBoard.selectedOptions[0].textContent}.`);
      $('#board-select').focus();
    } catch (error) { detailStatus(error.message, true); }
    finally { moving = false; transferBoard.disabled = false; transferColumn.disabled = !transferColumn.value; transferButton.disabled = transferColumn.disabled; [title, notes, column].forEach((el) => { el.disabled = false; }); $('#save-item').disabled = !dirty; updateCounts(); }
  });
  async function itemAction(deleting) {
    if (!selected || saving || moving) return;
    if (dirty) { detailStatus('Save the item’s changes before changing its state.', true); return; }
    if (deleting && !window.confirm(`Permanently delete “${selected.title}” and its history? This cannot be undone.`)) return;
    saving = true; updateCounts();
    const controls = [...detail.querySelectorAll('input, textarea, select, button')];
    const previous = controls.map((el) => el.disabled); controls.forEach((el) => { el.disabled = true; });
    try {
      const item = await api(selected.id, { method: deleting ? 'DELETE' : 'POST',
        body: JSON.stringify({ revision: selected.revision, cancelled: !selected.cancelled_at }) }, deleting ? '' : '/cancel');
      if (deleting) {
        cardFor(selected.id)?.remove(); selected = null; dirty = false; ++requestNumber;
        detail.hidden = true; $('.kanban-workspace').classList.remove('detail-open');
        announce('Item deleted.'); $('#board-select').focus();
      } else { updateCard(item); fillDetail(item); detailStatus(item.cancelled_at ? 'Item cancelled; history retained.' : 'Item restored.'); }
    } catch (error) { detailStatus(error.message, true); }
    finally { saving = false; controls.forEach((el, index) => { el.disabled = previous[index]; }); $('#save-item').disabled = !dirty; updateCounts(); }
  }
  $('#cancel-item').addEventListener('click', () => itemAction(false));
  $('#delete-item').addEventListener('click', () => itemAction(true));
  async function moveCard(card, zone, before = null) {
    if (moving || saving) return;
    if (search.value.trim()) { announce('Clear search before reordering cards.', true); return; }
    if (selected?.id === Number(card.dataset.item) && dirty) { announce('Save the open item’s changes before moving it.', true); return; }
    const origin = card.parentElement, next = card.nextElementSibling;
    if (origin === zone && (before === card || before === next)) return;
    moving = true; zone.insertBefore(card, before); updateCounts();
    try {
      const item = await api(card.dataset.item, { method: 'POST', body: JSON.stringify({ column_id: Number(zone.closest('[data-column]').dataset.column), before_id: before ? Number(before.dataset.item) : null, revision: Number(card.dataset.revision) }) }, '/move');
      updateCard(item);
      if (selected?.id === item.id) fillDetail(item);
      announce(`Moved “${item.title}” to ${zone.closest('[data-column]').querySelector('h2').textContent}, position ${cardsIn(zone).indexOf(card) + 1}.`);
    } catch (error) { origin.insertBefore(card, next); announce(error.message, true); }
    finally { moving = false; updateCounts(); }
  }
  board.addEventListener('click', (event) => {
    if (Date.now() < ignoreClickUntil) return;
    if (columnMode) {
      const control = event.target.closest('[data-column-step]');
      if (control) {
        const section = control.closest('.kanban-column');
        moveColumn(section, Number(control.dataset.columnStep) < 0 ? section.previousElementSibling : section.nextElementSibling?.nextElementSibling || null);
      }
      return;
    }
    const card = event.target.closest('.kanban-card'); if (!card) return;
    const direction = event.target.closest('[data-reorder]')?.dataset.reorder;
    if (direction) {
      const before = direction === 'up' ? card.previousElementSibling : card.nextElementSibling?.nextElementSibling;
      moveCard(card, card.parentElement, before || null);
    } else openItem(Number(card.dataset.item));
  });
  const clearTargets = () => board.querySelectorAll('.drop-before,.drop-at-end,.is-drop-target').forEach((el) => el.classList.remove('drop-before', 'drop-at-end', 'is-drop-target'));
  function dropBefore(zone, y) { return cardsIn(zone).filter((card) => card !== dragged).find((card) => y < card.getBoundingClientRect().top + card.getBoundingClientRect().height / 2) || null; }
  board.addEventListener('dragstart', (event) => {
    if (columnMode) {
      if (moving || saving) { event.preventDefault(); return; }
      draggedColumn = event.target.closest('.kanban-column');
      if (!draggedColumn) { event.preventDefault(); return; }
      event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', draggedColumn.dataset.column); return;
    }
    const card = event.target.closest('.kanban-card');
    if (!card || search.value.trim() || moving || saving || (selected?.id === Number(card.dataset.item) && dirty)) { event.preventDefault(); return; }
    dragged = card; card.classList.add('is-dragging'); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', card.dataset.item);
  });
  board.addEventListener('dragend', () => { dragged?.classList.remove('is-dragging'); dragged = null; draggedColumn = null; ignoreClickUntil = Date.now() + 200; clearTargets(); });
  board.addEventListener('dragover', (event) => { if (draggedColumn) { event.preventDefault(); event.dataTransfer.dropEffect = 'move'; } });
  board.addEventListener('drop', (event) => {
    if (!draggedColumn) return;
    event.preventDefault();
    const target = event.target.closest('.kanban-column');
    if (target && target !== draggedColumn) {
      const before = event.clientX < target.getBoundingClientRect().left + target.getBoundingClientRect().width / 2 ? target : target.nextElementSibling;
      moveColumn(draggedColumn, before);
    }
    draggedColumn = null; ignoreClickUntil = Date.now() + 200;
  });
  board.querySelectorAll('.kanban-dropzone').forEach((zone) => {
    zone.addEventListener('dragover', (event) => {
      if (!dragged) return;
      event.preventDefault(); event.dataTransfer.dropEffect = 'move'; clearTargets(); zone.classList.add('is-drop-target');
      const before = dropBefore(zone, event.clientY);
      if (before) before.classList.add('drop-before'); else zone.classList.add('drop-at-end');
    });
    zone.addEventListener('dragleave', (event) => { if (!zone.contains(event.relatedTarget)) clearTargets(); });
    zone.addEventListener('drop', (event) => {
      if (!dragged) return;
      event.preventDefault(); const card = dragged, before = dropBefore(zone, event.clientY);
      clearTargets(); card.classList.remove('is-dragging'); dragged = null; ignoreClickUntil = Date.now() + 200;
      moveCard(card, zone, before);
    });
  });
  $('#board-select')?.addEventListener('change', (event) => {
    if (canLeave()) { dirty = false; location.href = event.target.value; }
    else event.target.value = [...event.target.options].find((option) => option.defaultSelected)?.value || '';
  });
  document.querySelectorAll('.new-card form').forEach((newForm) => newForm.addEventListener('submit', (event) => { if (!canLeave()) event.preventDefault(); else dirty = false; }));
  window.addEventListener('beforeunload', (event) => { if (dirty || saving || moving || commentSaving || $('#comment-body').value.trim()) { event.preventDefault(); event.returnValue = ''; } });
  search.addEventListener('input', updateCounts);
  $('#clear-kanban-search').addEventListener('click', () => { search.value = ''; updateCounts(); search.focus(); });
  updateCounts();
  window.addEventListener('popstate',()=>{
    const id=new URLSearchParams(location.search).get('item');
    if(!canLeave()){itemAddress(selected?.id);return;}
    dirty=false;$('#comment-body').value='';
    if(id&&cardFor(Number(id)))openItem(Number(id));else{closeDetail();if(id)announce('Item not found on this board.',true);}
  });
  const linkedItem = new URLSearchParams(location.search).get('item');
  if (/^\d+$/.test(linkedItem || '') && cardFor(Number(linkedItem))) openItem(Number(linkedItem));
})();
