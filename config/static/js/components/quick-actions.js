(() => {
    const root = document.querySelector('[data-quick-actions]');
    if (!root) return;

    const fab = root.querySelector('[data-quick-actions-toggle]');
    const actions = root.querySelectorAll('.babaei-quick-actions__action');
    if (!fab) return;

    const setOpen = (open) => {
        root.classList.toggle('is-open', open);
        fab.setAttribute('aria-expanded', String(open));
        fab.setAttribute(
            'aria-label',
            open ? 'بستن دسترسی‌های سریع' : 'باز کردن دسترسی‌های سریع'
        );
    };

    fab.addEventListener('click', () => {
        setOpen(!root.classList.contains('is-open'));
    });

    document.addEventListener('pointerdown', (event) => {
        if (!root.contains(event.target)) setOpen(false);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && root.classList.contains('is-open')) {
            setOpen(false);
            fab.focus();
        }
    });

    actions.forEach((action) => {
        action.addEventListener('click', () => {
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
            action.animate(
                [
                    { transform: 'scale(.86)' },
                    { transform: 'scale(1)' },
                ],
                {
                    duration: 220,
                    easing: 'cubic-bezier(.34, 1.4, .4, 1)',
                }
            );
        });
    });
})();
