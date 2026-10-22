/* Runtime companion for the mobile 3D studio fixes. */
(() => {
    "use strict";
    const stage = document.getElementById("designer-3d-stage");
    const canvas = document.getElementById("designer-3d-canvas");
    const workspace = document.querySelector(".customizer-workspace--premium");
    if (!stage || !canvas || !workspace) return;

    const syncViewport = () => {
        const rect = stage.getBoundingClientRect();
        if (rect.width < 1 || rect.height < 1) return;
        canvas.style.width = `${Math.round(rect.width)}px`;
        canvas.style.height = `${Math.round(rect.height)}px`;
        window.dispatchEvent(new Event("resize"));
    };

    const observer = new ResizeObserver(syncViewport);
    observer.observe(stage);
    window.addEventListener("orientationchange", () => setTimeout(syncViewport, 80), { passive: true });
    document.addEventListener("babaei:drawer-state", () => setTimeout(syncViewport, 180));

    // Never leave a modal-looking sheet/backdrop active after a close tap.
    document.querySelectorAll("[data-drawer-close]").forEach(button => {
        button.addEventListener("click", () => setTimeout(() => {
            workspace.classList.remove("mobile-drawer-open");
            document.body.classList.remove("customizer-mobile-sheet-open");
            syncViewport();
        }, 0);
    });

    syncViewport();
})();
