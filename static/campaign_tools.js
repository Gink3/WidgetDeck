(() => {
  document.querySelectorAll('[data-open-dialog]').forEach((button) => {
    button.addEventListener('click', () => document.querySelector(`#${button.dataset.openDialog}`)?.showModal());
  });
  document.querySelectorAll('[data-close-dialog]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
  });

  const addField = (selector, containerSelector, fieldName, controls = '') => {
    const button = document.querySelector(selector);
    const container = document.querySelector(containerSelector);
    if (!button || !container) return;
    button.addEventListener('click', () => {
      const row = document.createElement('div');
      const input = document.createElement('input');
      input.name = fieldName;
      input.placeholder = fieldName.replace('_', ' ');
      row.append(input);
      if (controls) row.insertAdjacentHTML('beforeend', controls);
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'remove-field';
      remove.textContent = '×';
      remove.setAttribute('aria-label', 'Remove field');
      remove.addEventListener('click', () => row.remove());
      row.append(remove);
      container.append(row);
      input.focus();
    });
  };

  addField('[data-add-rdt-field]', '#rdt-fields', 'field_name', '<select name="field_metric"><option value="none">No metric</option><option value="average">Average</option><option value="sum">Sum</option><option value="count">Count filled</option></select>');
  addField('[data-add-kanban-column]', '#kanban-columns', 'column_name');

})();
