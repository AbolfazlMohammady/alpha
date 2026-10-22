/*
 * Portrait framing helper.
 * Loaded after the procedural renderer and asks it to refit after mobile
 * layout changes without applying CSS transforms to the WebGL canvas.
 */
(() => {
    "use strict";
    const stage = document.getElementById("designer-3d-stage");
    if (!stage) return;

    const refit = () => {
        window.BabaeiCustomizer3D?.refit?.();
    };

    const observer = new ResizeObserver(() => requestAnimationFrame(refit));
    observer.observe(stage);
    window.addEventListener("orientationchange", () => setTimeout(refit, 120), { passive: true });
    window.addEventListener("resize", () => setTimeout(refit, 60), { passive: true });
    window.addEventListener("pageshow", refit, { once: true });
})();
