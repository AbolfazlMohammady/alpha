/* ==========================================================================
   BABAEI — product photo tilt
   --------------------------------------------------------------------------
   Desktop mouse interaction for the main product photo. The implementation
   follows the requested React/shadcn card behaviour, adapted to this Django
   + plain JS project:
   - up to 8deg tilt toward the pointer
   - subtle scale lift while interacting
   - cursor-following soft highlight
   - no motion when the OS asks for reduced motion
   - touch pointers are ignored
   ========================================================================== */
(() => {
    "use strict";

    const card = document.querySelector("[data-product-tilt]");
    if (!card) return;

    const MAX_TILT = 8;
    const noMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    let rafId = 0;
    let pointer = null;
    let active = false;

    const render = () => {
        rafId = 0;
        if (!pointer || noMotion.matches) return;

        const rect = card.getBoundingClientRect();
        if (!rect.width || !rect.height) return;

        const px = Math.max(0, Math.min(1, (pointer.x - rect.left) / rect.width));
        const py = Math.max(0, Math.min(1, (pointer.y - rect.top) / rect.height));

        const rotateX = (0.5 - py) * 2 * MAX_TILT;
        const rotateY = (px - 0.5) * 2 * MAX_TILT;

        card.style.setProperty("--tilt-x", `${rotateX.toFixed(2)}deg`);
        card.style.setProperty("--tilt-y", `${rotateY.toFixed(2)}deg`);
        card.style.setProperty("--glow-x", `${(px * 100).toFixed(1)}%`);
        card.style.setProperty("--glow-y", `${(py * 100).toFixed(1)}%`);
    };

    const queueRender = () => {
        if (!rafId) rafId = window.requestAnimationFrame(render);
    };

    const reset = () => {
        pointer = null;
        active = false;
        card.classList.remove("is-tilting");
        card.style.setProperty("--tilt-x", "0deg");
        card.style.setProperty("--tilt-y", "0deg");
        card.style.setProperty("--glow-x", "50%");
        card.style.setProperty("--glow-y", "50%");
        card.style.setProperty("--tilt-lift", "1");
    };

    const move = (event) => {
        // Ignore non-mouse pen/touch pointers when a PointerEvent is supplied.
        if (event.pointerType && event.pointerType !== "mouse") return;

        if (noMotion.matches) {
            reset();
            return;
        }

        pointer = { x: event.clientX, y: event.clientY };

        if (!active) {
            active = true;
            card.classList.add("is-interactive");
            card.classList.add("is-tilting");
            card.style.setProperty("--tilt-lift", "1.025");
        }

        queueRender();
    };

    const leave = () => reset();

    // Pointer events are the primary path. mouse events are kept as a browser
    // fallback because some desktop browser/extension combinations can report
    // an unusable hover media-query state while still delivering mouse events.
    card.addEventListener("pointermove", move, { passive: true });
    card.addEventListener("pointerleave", leave, { passive: true });
    card.addEventListener("mousemove", move, { passive: true });
    card.addEventListener("mouseleave", leave, { passive: true });

    noMotion.addEventListener("change", () => {
        if (noMotion.matches) reset();
    });

    card.classList.add("is-interactive");
    card.style.setProperty("--tilt-x", "0deg");
    card.style.setProperty("--tilt-y", "0deg");
    card.style.setProperty("--glow-x", "50%");
    card.style.setProperty("--glow-y", "50%");
    card.style.setProperty("--tilt-lift", "1");
})();