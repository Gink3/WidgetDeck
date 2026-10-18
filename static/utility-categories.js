(() => {
  const panel = document.querySelector('#utility-categories-panel');
  if (!panel) return;
  const status = panel.querySelector('#utility-category-status');
  const form = panel.querySelector('#utility-category-create');
  let token = '', busy = false;
  const element = (tag, text) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; return node; };
  function render(state) {
    const list = panel.querySelector('#utility-category-list');
    list.replaceChildren();
    for (const category of state.categories) {
      const item = element('div');
      item.className = 'category-item';
      item.append(element('span', category.name));
      if (!category.default) {
        const button = element('button', 'Delete');
        button.type = 'button';
        button.setAttribute('aria-label', 'Delete category ' + category.name);
        button.addEventListener('click', () => change('/api/launcher/categories/' + category.id, 'DELETE'));
        item.append(button);
      }
      list.append(item);
    }
    const assignments = panel.querySelector('#utility-category-assignments');
    assignments.replaceChildren();
    for (const utility of state.utilities) {
      const row = element('label');
      row.className = 'category-assignment';
      row.append(element('span', utility.label));
      const select = element('select');
      select.dataset.utility = utility.id;
      select.setAttribute('aria-label', 'Category for ' + utility.label);
      const defaultOption = element('option', 'Use widget default (' + utility.default_category + ')');
      defaultOption.value = '';
      select.append(defaultOption);
      for (const category of state.categories) {
        const option = element('option', category.name);
        option.value = category.name;
        select.append(option);
      }
      select.value = utility.override || '';
      select.addEventListener('change', () => change('/api/launcher/categories/utilities/' + encodeURIComponent(utility.id), 'PUT', { category: select.value || null }));
      row.append(select);
      assignments.append(row);
    }
  }
  async function change(url, method, payload) {
    if (busy) return;
    busy = true;
    panel.querySelectorAll('button,input,select').forEach(node => { node.disabled = true; });
    status.textContent = 'Saving…';
    try {
      const response = await fetch(url, { method, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token }, body: payload ? JSON.stringify(payload) : undefined });
      const state = await response.json();
      if (!response.ok) throw new Error(state.error || 'Unable to save categories.');
      render(state);
      if (method === 'POST') form.reset();
      status.textContent = 'Categories saved. Your Dashboard and Utilities menu use these choices when you open or reload a page.';
    } catch (error) {
      status.textContent = error.message;
      // Restore the saved selections after a rejected write.
      try { const response = await fetch('/api/launcher/categories'); if (response.ok) { const state = await response.json(); token = state.csrf_token; render(state); } } catch (_) {}
    } finally {
      busy = false;
      panel.querySelectorAll('button,input,select').forEach(node => { node.disabled = false; });
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); change('/api/launcher/categories', 'POST', { name: form.elements.name.value }); });
  fetch('/api/launcher/categories').then(async response => {
    const state = await response.json();
    if (!response.ok) throw new Error(state.error || 'Unable to load categories.');
    token = state.csrf_token;
    render(state);
    status.textContent = '';
  }).catch(error => { status.textContent = error.message; });
})();
