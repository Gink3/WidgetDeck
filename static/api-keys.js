(() => {
  const form = document.querySelector('#api-key-form');
  if (!form) return;
  const status = document.querySelector('#api-key-status');
  const list = document.querySelector('#api-key-list');
  const secret = document.querySelector('#api-key-secret');
  const token = document.querySelector('#api-key-token');
  const controls = document.querySelector('#api-key-services');
  let csrf = '', services = {};
  const api = async (path = '', options = {}) => {
    const response = await fetch(`/api/account/keys${path}`, {...options, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}});
    const data = response.status === 204 ? {} : await response.json();
    if (!response.ok) throw Error(data.error || 'Could not manage API keys.');
    return data;
  };
  const load = async () => {
    const data = await api();
    csrf = data.csrf_token;
    services = data.services;
    if (!controls.children.length) Object.entries(services).forEach(([id, name]) => {
      const label = document.createElement('label');
      label.textContent = name;
      const select = document.createElement('select');
      select.name = id; select.setAttribute('aria-label', name);
      [['', 'No access'], ['read', 'Read only'], ['write', 'Read and write']].forEach(([value, text]) => select.add(new Option(text, value)));
      label.append(select); controls.append(label);
    });
    list.replaceChildren();
    if (!data.keys.length) list.textContent = 'You have no API keys.';
    data.keys.forEach(key => {
      const card = document.createElement('article'); card.className = 'panel';
      const title = document.createElement('h3'); title.textContent = key.name;
      const details = document.createElement('p');
      details.textContent = `${key.prefix}… · Created ${new Date(key.created_at).toLocaleDateString()} · ` + Object.entries(key.permissions).map(([id, mode]) => `${services[id] || id}: ${mode === 'write' ? 'read and write' : 'read only'}`).join(', ');
      const revoke = document.createElement('button'); revoke.type = 'button'; revoke.textContent = 'Revoke key';
      revoke.addEventListener('click', async () => {
        if (!confirm(`Revoke “${key.name}”? Integrations using it will lose access immediately.`)) return;
        revoke.disabled = true;
        try { await api(`/${key.id}`, {method: 'DELETE'}); secret.hidden = true; token.value = ''; await load(); status.textContent = 'Key revoked.'; }
        catch (error) { status.textContent = error.message; revoke.disabled = false; }
      });
      card.append(title, details, revoke); list.append(card);
    });
  };
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button'); button.disabled = true;
    secret.hidden = true; token.value = '';
    try {
      const permissions = Object.fromEntries([...controls.querySelectorAll('select')].filter(select => select.value).map(select => [select.name, select.value]));
      const data = await api('', {method: 'POST', body: JSON.stringify({name: form.elements.name.value, permissions})});
      token.value = data.token; secret.hidden = false; token.focus(); token.select();
      form.reset(); status.textContent = 'Key created. Save it before leaving this page.'; await load();
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.querySelector('#api-key-dismiss').addEventListener('click', () => { token.value = ''; secret.hidden = true; });
  load().catch(error => { status.textContent = error.message; });
})();
