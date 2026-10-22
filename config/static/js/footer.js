/* =========================================================================
   SITE FOOTER
   The behaviour behind includes/footer.html. Vanilla, because this project
   has no React, no Tailwind and no GSAP: what was ported from the component
   the footer design comes from is the effect, not the stack.

   Everything is gated on the footer existing, and nothing runs while it is
   off screen except the three cheap things that must: reveal, scroll-linked
   depth for the giant text, and the magnetic pills on a fine pointer.
   ========================================================================= */
const setupSiteFooter = () => {
    const footer = document.querySelector("[data-site-footer]");
    if (!footer) return;

    const stage = footer.closest("[data-footer-stage]") || footer;
    const blocks = footer.querySelectorAll("[data-ft-reveal]");
    const giant = footer.querySelector("[data-footer-giant]");
    const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // One observer + one rAF-driven scroll loop. Nothing is watched or
    // recalculated while the footer is far away from the viewport.
    if ("IntersectionObserver" in window) {
        footer.classList.add("is-animated");

        let ticking = false;
        let active = false;

        const paint = () => {
            ticking = false;

            if (!active) return;

            const box = stage.getBoundingClientRect();
            const travel = box.height + window.innerHeight;
            if (travel <= 0) return;

            const progress = Math.min(
                1,
                Math.max(0, (window.innerHeight - box.top) / travel)
            );

            footer.style.setProperty("--ft-p", progress.toFixed(3));
            footer.classList.toggle("is-visible", progress > 0.08);
        };

        const requestPaint = () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(paint);
        };

        const watcher = new IntersectionObserver((entries) => {
            const entry = entries[entries.length - 1];
            active = Boolean(entry?.isIntersecting);

            if (active) {
                requestPaint();
            } else {
                footer.classList.remove("is-visible");
            }
        }, { rootMargin: "240px 0px" });

        watcher.observe(stage);

        window.addEventListener("scroll", requestPaint, { passive: true });
        window.addEventListener("resize", requestPaint, { passive: true });

        if (calm) {
            footer.classList.add("is-visible");
            footer.style.setProperty("--ft-p", "1");
        }
    } else {
        footer.classList.add("is-visible");
        footer.style.setProperty("--ft-p", "1");
    }

    // Magnetic interaction exists only on a fine pointer. Touch devices pay
    // no per-pointer work at all.
    if (!calm && window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
        footer.querySelectorAll("[data-magnet]").forEach((pill) => {
            let rect = null;
            let pending = false;
            let pointer = null;

            const invalidate = () => { rect = null; };

            const paintMagnet = () => {
                pending = false;
                if (!pointer) return;

                rect ||= pill.getBoundingClientRect();
                if (!rect.width || !rect.height) return;

                const dx = (pointer.x - (rect.left + rect.width / 2)) * 0.2;
                const dy = (pointer.y - (rect.top + rect.height / 2)) * 0.26;

                pill.style.transform =
                    `translate3d(${dx.toFixed(1)}px, ${dy.toFixed(1)}px, 0)`;
                pointer = null;
            };

            pill.addEventListener("pointerenter", invalidate, { passive: true });
            pill.addEventListener("pointermove", (event) => {
                pointer = { x: event.clientX, y: event.clientY };
                if (pending) return;

                pending = true;
                window.requestAnimationFrame(paintMagnet);
            }, { passive: true });
            pill.addEventListener("pointerleave", () => {
                pointer = null;
                pill.style.transform = "";
                rect = null;
            });
        });
    }
};

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupSiteFooter, { once: true });
} else {
    setupSiteFooter();
}
