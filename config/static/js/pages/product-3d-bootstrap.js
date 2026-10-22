(() => {
    "use strict";

    const root = document.getElementById("customizer");
    const loading = document.getElementById("designer-3d-loading");
    const progress = document.getElementById("designer-3d-progress");
    const progressBar = document.getElementById("designer-3d-progress-bar");
    const progressText = document.getElementById("designer-3d-progress-text");
    const retryButton = document.getElementById("designer-3d-retry");
    if (!root || !loading || !progress) return;

    const data = JSON.parse(document.getElementById("designer-data")?.textContent || "{}");
    const generation = data.generation || {};
    const prepareUrl = root.dataset.threeDPrepareUrl;
    const statusUrl = root.dataset.threeDStatusUrl;
    const csrf = () => {
        const cookie = document.cookie.split(";").map((item) => item.trim()).find((item) => item.startsWith("csrftoken="));
        return cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "";
    };

    let timer = null;
    let starting = false;
    let polling = false;
    let reloadScheduled = false;

    function setProgress(value, text) {
        const percent = Math.max(0, Math.min(100, Number(value) || 0));
        progress.classList.remove("is-hidden");
        if (progressBar) progressBar.style.width = `${Math.max(4, percent)}%`;
        if (progressText) progressText.textContent = text;
        if (loading) loading.textContent = text;
    }

    function setFailed(message) {
        stopPolling();
        setProgress(0, message || "ساخت مدل سه‌بعدی انجام نشد.");
        retryButton?.classList.remove("is-hidden");
    }

    function stopPolling() {
        if (timer) {
            window.clearInterval(timer);
            timer = null;
        }
        polling = false;
    }

    function scheduleReload() {
        if (reloadScheduled) return;
        reloadScheduled = true;
        stopPolling();
        window.setTimeout(() => window.location.reload(), 700);
    }

    function startPolling() {
        if (polling || !statusUrl || reloadScheduled) return;
        polling = true;
        timer = window.setInterval(poll, 8000);
    }

    async function poll() {
        if (!statusUrl || reloadScheduled || document.hidden) return;
        try {
            const response = await fetch(statusUrl, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "وضعیت مدل دریافت نشد.");

            if (result.ready || result.status === "ready") {
                setProgress(100, "مدل آماده شد؛ محیط سه‌بعدی در حال ورود است…");
                scheduleReload();
                return;
            }

            if (result.status === "failed") {
                setFailed(result.error || "ساخت مدل سه‌بعدی ناموفق بود.");
                return;
            }

            const text = result.status === "removing_background"
                ? "در حال حذف هوشمند پس‌زمینه تصاویر…"
                : result.status === "generating"
                    ? `در حال ساخت مدل سه‌بعدی… ${result.progress || 0}%`
                    : result.status === "queued"
                        ? "مدل در صف پردازش قرار گرفت…"
                        : "در حال آماده‌سازی مدل سه‌بعدی…";
            setProgress(result.progress || 8, text);
        } catch (error) {
            // A temporary status request failure must not restart the generation job.
            setProgress(generation.progress || 8, "در حال اتصال به پردازشگر سه‌بعدی…");
        }
    }

    async function prepare() {
        if (starting || !prepareUrl || reloadScheduled) return;
        starting = true;
        retryButton?.classList.add("is-hidden");
        setProgress(4, "در حال تحلیل تصاویر محصول…");

        try {
            const response = await fetch(prepareUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrf(), "Accept": "application/json" },
                credentials: "same-origin",
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "آماده‌سازی مدل انجام نشد.");

            if (result.status === "ready") {
                if (result.source === "manual") {
                    // Manual GLB/GLTF is already part of the page data. Do not reload,
                    // otherwise the page can enter a prepare -> reload loop.
                    progress.classList.add("is-hidden");
                    loading.textContent = "مدل سه‌بعدی آماده است.";
                    stopPolling();
                    return;
                }
                setProgress(100, "مدل آماده شد؛ محیط سه‌بعدی در حال ورود است…");
                scheduleReload();
                return;
            }

            const text = result.status === "removing_background"
                ? "در حال حذف هوشمند پس‌زمینه تصاویر…"
                : result.status === "generating"
                    ? "در حال ساخت مدل سه‌بعدی…"
                    : "مدل در صف پردازش قرار گرفت…";
            setProgress(result.progress || 8, text);
            startPolling();
            await poll();
        } catch (error) {
            setFailed(error.message);
        } finally {
            starting = false;
        }
    }

    retryButton?.addEventListener("click", () => prepare());

    const hasModel = (data.views || []).some((view) => view.model);
    if (hasModel || generation.ready) {
        progress.classList.add("is-hidden");
        stopPolling();
        return;
    }

    setProgress(
        generation.progress || 4,
        generation.status === "generating"
            ? "در حال ساخت مدل سه‌بعدی…"
            : generation.status === "queued"
                ? "مدل در صف پردازش قرار گرفت…"
                : "در حال تحلیل محصول و آماده‌سازی مدل…"
    );

    // Exactly one prepare request per page lifecycle. All subsequent checks use
    // the read-only status endpoint every five seconds.
    prepare();
    window.addEventListener("beforeunload", stopPolling, { once: true });
})();
