(() => {
  const menus = [...document.querySelectorAll('nav .nav-menu')];

  const search = document.querySelector('#utility-menu-search');
  if (search) search.addEventListener('input',() => {
    const words = search.value.trim().toLocaleLowerCase().split(/\s+/);
    const links = [...document.querySelectorAll('.utility-menu-group a')];
    links.forEach(link => { link.hidden = !words.every(word => link.dataset.search.toLocaleLowerCase().includes(word)); });
    document.querySelectorAll('.utility-menu-group').forEach(group => { group.hidden = ![...group.querySelectorAll('a')].some(link => !link.hidden); });
    document.querySelector('#utility-menu-empty').hidden = links.some(link => !link.hidden);
  });
  document.addEventListener('keydown',event => { if (event.key === 'Escape'){const active=event.target.closest('nav .nav-menu[open]');menus.forEach(menu => { menu.open = false; });if(active)active.querySelector('summary')?.focus();} });
  document.addEventListener('click',event => { if (!event.target.closest('.nav-menu')) menus.forEach(menu => { menu.open = false; }); });
  menus.forEach((menu) => {
    menu.addEventListener('toggle', () => {
      if (!menu.open) return;
      menus.forEach((otherMenu) => {
        if (otherMenu !== menu) otherMenu.open = false;
      });
    });
  });
})();
