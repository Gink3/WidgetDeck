(() => {
  const form = document.querySelector('.converter-form');
  if (!form || !window.fetch || !window.URL?.createObjectURL) return;
  const input = form.elements.images, format = form.elements.format;
  const submit = form.querySelector('[type=submit]');
  const status = document.querySelector('#converter-status');
  const files = document.querySelector('#converter-files');
  const result = document.querySelector('#converter-result');
  const save = document.querySelector('#converter-save');
  const share = document.querySelector('#converter-share');
  const login = document.querySelector('#converter-login');
  const previews = [];
  let outputUrl, outputFile, busy = false;
  submit.textContent = 'Convert images';
  function clearResult() {
    if (outputUrl) URL.revokeObjectURL(outputUrl);
    outputUrl = null; outputFile = null; result.hidden = true; share.hidden = true;
    save.removeAttribute('href');
  }
  function selected() {
    clearResult();
    previews.splice(0).forEach(url => URL.revokeObjectURL(url));
    files.replaceChildren();
    const chosen = [...input.files];
    const bytes = chosen.reduce((total, file) => total + file.size, 0);
    let error = chosen.length > 30 ? 'Choose no more than 30 images at once.' : '';
    if (chosen.some(file => !file.size || file.size > 30 * 1024 * 1024)) error = 'Each image must contain data and be no larger than 30 MB.';
    if (bytes > 100 * 1024 * 1024) error = 'The total upload size must be no larger than 100 MB.';
    if (chosen.some(file => /\.hei[cf]$/i.test(file.name))) error = 'HEIC/HEIF is not supported here. Export the photo as JPEG or PNG first.';
    input.setCustomValidity(error);
    submit.disabled = Boolean(error);
    document.querySelector('#converter-selection').textContent = chosen.length
      ? `${chosen.length} image${chosen.length === 1 ? '' : 's'} selected · ${(bytes / 1024 / 1024).toFixed(1)} MB` : '';
    status.textContent = error;
    chosen.slice(0, 6).forEach(file => {
      const row = document.createElement('li');
      const name = document.createElement('span');
      name.textContent = file.name;
      if (/^image\/(png|jpeg|webp|avif|bmp)$/.test(file.type)) {
        const image = document.createElement('img');
        image.alt = ''; image.loading = 'lazy';
        image.src = URL.createObjectURL(file); previews.push(image.src);
        image.addEventListener('error', () => image.remove(), { once: true });
        row.append(image);
      }
      row.append(name); files.append(row);
    });
    if (chosen.length > 6) {
      const more = document.createElement('li'); more.textContent = `And ${chosen.length - 6} more images`; files.append(more);
    }
  }
  input.addEventListener('change', selected);
  format.addEventListener('change', clearResult);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !form.reportValidity()) return;
    const payload = new FormData(form);
    busy = true; clearResult(); login.hidden = true;
    input.disabled = format.disabled = submit.disabled = true;
    form.setAttribute('aria-busy', 'true');
    status.textContent = 'Uploading and converting… Keep this app open.';
    try {
      const response = await fetch(form.action, { method: 'POST', body: payload, headers: { Accept: 'application/json' } });
      if (response.status === 401 || (response.redirected && new URL(response.url).pathname === '/login')) {
        login.hidden = false;
        throw new Error('Your session expired. Sign in, then try again; your selected files stay here.');
      }
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.error || `Conversion failed (${response.status}). Try fewer or smaller files.`);
      }
      const type = response.headers.get('Content-Type') || '';
      if (!type.startsWith('image/') && !type.startsWith('application/zip')) throw new Error('The server did not return an image or ZIP. Please try again.');
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const name = disposition.match(/filename="?([^";]+)"?/)?.[1] || 'converted-image';
      outputUrl = URL.createObjectURL(blob);
      outputFile = new File([blob], name, { type: blob.type });
      save.href = outputUrl; save.download = name;
      document.querySelector('#converter-result-name').textContent = `${name} · ${(blob.size / 1024 / 1024).toFixed(1)} MB`;
      result.hidden = false;
      try { share.hidden = !navigator.canShare?.({ files: [outputFile] }); } catch (_) { share.hidden = true; }
      status.textContent = 'Conversion complete. Save or share your file below.';
      save.focus({ preventScroll: true });
    } catch (error) {
      status.textContent = error instanceof TypeError ? 'Connection lost. Your files have not been queued. Reconnect and try again.' : error.message;
    } finally {
      busy = false; input.disabled = format.disabled = submit.disabled = false;
      form.removeAttribute('aria-busy');
    }
  });
  share.addEventListener('click', async () => {
    if (!outputFile) return;
    try { await navigator.share({ files: [outputFile] }); }
    catch (error) { if (error.name !== 'AbortError') status.textContent = 'Sharing is unavailable. Use Save file instead.'; }
  });
})();
