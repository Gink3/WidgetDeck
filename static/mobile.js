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

  let frame;
  function viewportChanged() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const viewport = window.visualViewport;
      // Pinch zoom keeps native page positioning; do not shrink dialogs into it.
      const normalScale = !viewport || Math.abs(viewport.scale - 1) < 0.01;
      const height = normalScale && viewport ? viewport.height : innerHeight;
      const top = normalScale && viewport ? viewport.offsetTop : 0;
      document.documentElement.style.setProperty('--mobile-viewport-height', `${height}px`);
      document.documentElement.style.setProperty('--mobile-viewport-top', `${top}px`);
      const field = document.activeElement;
      if (matchMedia('(max-width: 800px)').matches && normalScale &&
          field?.matches('input:not([type=checkbox],[type=radio]),textarea,select')) {
        const rect = field.getBoundingClientRect();
        if (rect.bottom > top + height - 12 || rect.top < top) {
          field.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
      }
    });
  }
  window.visualViewport?.addEventListener('resize', viewportChanged);
  window.visualViewport?.addEventListener('scroll', viewportChanged);
  window.addEventListener('resize', viewportChanged);
  document.addEventListener('focusin', viewportChanged);
  viewportChanged();
})();
