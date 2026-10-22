/* ==========================================================================
   BABAEI — Mobile dock indicator
   --------------------------------------------------------------------------
   Slides the green capsule under the row marked aria-current="page".

   The row itself is chosen by the server, so this file never decides state — it
   only measures. Uses inset-inline-start so the direction is handled by the
   browser instead of by sign-flipping arithmetic on a transform.
   ========================================================================== */
(() => {
    const dock = document.querySelector("[data-sh-dock]");
    if (!dock) return;

    const pill = dock.querySelector("[data-sh-dock-pill]");
    const items = Array.from(dock.querySelectorAll("[data-sh-dock-item]"));
    if (!pill || !items.length) return;

    const place = (animate) => {
        const active =
            dock.querySelector('[data-sh-dock-item][aria-current="page"]') || items[0];
        if (!active) return;

        const item = active.getBoundingClientRect();
        const base = dock.getBoundingClientRect();
        // Distance from the dock's inline start edge (= right edge in RTL).
        const offset = base.right - item.right - (parseFloat(getComputedStyle(dock).paddingInlineEnd) || 0) + 6;

        pill.style.insetInlineStart = `${offset}px`;
        // Height, not width: the indicator has to stay circular.
        pill.style.inlineSize = `${item.height}px`;

        if (animate) dock.setAttribute("data-ready", "");
    };

    place(false);

    // Re-measure once the webfont has settled, otherwise the label under the
    // active icon can change the item width after the first paint.
    if (document.fonts && document.fonts.ready) {
        document.fonts.ready.then(() => place(true));
    }

    let raf = 0;
    const schedule = () => {
        if (raf) return;
        raf = requestAnimationFrame(() => {
            raf = 0;
            place(true);
        });
    };

    window.addEventListener("resize", schedule, { passive: true });
    window.addEventListener("orientationchange", schedule, { passive: true });
})();
