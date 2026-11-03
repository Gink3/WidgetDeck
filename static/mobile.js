/* Use the right on-screen keyboard without changing existing form values/types. */
(() => {
  let dialogHeading=0;
  function prepare(root) {
    // Native dialogs need an explicit name; retain names supplied by widgets.
    for(const dialog of root.querySelectorAll('dialog:not([aria-label]):not([aria-labelledby]):not([title])')){
      const heading=dialog.querySelector('h1,h2,h3');if(!heading)continue;
      if(!heading.id){do{dialogHeading++;}while(document.getElementById('mobile-dialog-heading-'+dialogHeading));heading.id='mobile-dialog-heading-'+dialogHeading;}
      dialog.setAttribute('aria-labelledby',heading.id);
    }
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

  const navigation = document.querySelector('#main-navigation');
  const toggle = document.querySelector('#mobile-nav-toggle');
  if (navigation && toggle) {
    const phone = matchMedia('(max-width: 720px)');
    let expanded = false;
    function renderNavigation() {
      document.body.classList.toggle('mobile-nav-ready', phone.matches);
      toggle.hidden = !phone.matches;
      navigation.hidden = phone.matches && !expanded;
      toggle.setAttribute('aria-expanded', String(phone.matches && expanded));
    }
    toggle.addEventListener('click', () => {
      expanded = !expanded;
      renderNavigation();
      if (expanded) navigation.querySelector('button,a,summary')?.focus();
    });
    phone.addEventListener('change', () => { expanded = false; renderNavigation(); });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !event.defaultPrevented && phone.matches && expanded &&
          !event.target.closest('dialog')) {
        expanded = false; renderNavigation(); toggle.focus();
      }
    });
    document.addEventListener('click', event => {
      if (phone.matches && expanded && !event.target.closest('body > header,dialog')) {
        expanded = false; renderNavigation();
      }
    });
    renderNavigation();
  }
})();
