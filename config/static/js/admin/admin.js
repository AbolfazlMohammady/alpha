(() => {
  const sidebar=document.querySelector('[data-admin-sidebar]');
  const overlay=document.querySelector('[data-admin-overlay]');
  const open=document.querySelector('[data-admin-menu]');
  const close=document.querySelector('[data-admin-close]');
  const setMenu=(state)=>{
    sidebar?.classList.toggle('is-open',state);
    overlay?.classList.toggle('is-visible',state);
    open?.setAttribute('aria-expanded',String(state));
    document.body.classList.toggle('ba-menu-open',state);
  };
  open?.addEventListener('click',()=>setMenu(!sidebar?.classList.contains('is-open')));
  close?.addEventListener('click',()=>setMenu(false));
  overlay?.addEventListener('click',()=>setMenu(false));

  document.querySelectorAll('[data-admin-group]').forEach((button)=>{
    button.addEventListener('click',()=>button.closest('.ba-nav-group')?.classList.toggle('is-collapsed'));
  });

  document.querySelectorAll('.ba-nav-group').forEach((group)=>{
    if(group.querySelector('.ba-nav-item.is-active')) group.classList.add('is-current');
  });

  const user=document.querySelector('[data-admin-user]');
  const menu=document.querySelector('[data-admin-user-menu]');
  user?.addEventListener('click',(event)=>{
    event.stopPropagation();
    const state=!menu?.classList.contains('is-open');
    menu?.classList.toggle('is-open',state);
    user.setAttribute('aria-expanded',String(state));
  });
  menu?.addEventListener('click',(event)=>event.stopPropagation());
  document.addEventListener('click',()=>{
    menu?.classList.remove('is-open');
    user?.setAttribute('aria-expanded','false');
  });

  document.querySelectorAll('.ba-sidebar a').forEach((link)=>{
    link.addEventListener('click',()=>{ if(window.innerWidth<=980) setMenu(false); });
  });

  window.addEventListener('resize',()=>{
    if(window.innerWidth>980) setMenu(false);
  });
})();