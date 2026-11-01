/* Use the right on-screen keyboard without changing existing form values/types. */
(() => {
  function prepare(root) {
    const fields = root.querySelectorAll('input[type="number"]:not([inputmode])');
    for (const field of fields) {
      field.inputMode = field.step === 'any' || (field.step && !Number.isInteger(Number(field.step)))
        ? 'decimal' : 'numeric';
    }
  }
  prepare(document);
  new MutationObserver(records => {
    if (records.some(record => record.addedNodes.length)) prepare(document);
  }).observe(document.body, { childList: true, subtree: true });
})();
