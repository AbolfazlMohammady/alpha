/*
 * "Designs" library: a template picker (text, badges, icons, patterns) opened
 * from the bottom toolbar. Clicking a template rasterises it to a transparent
 * PNG, uploads it through the normal artwork endpoint (so saving and ordering
 * work exactly like any uploaded label) and adds it to the garment.
 */
(() => {
    "use strict";

    const CATEGORIES = [
        ["all", "همه"],
        ["text", "متن"],
        ["badges", "نشان‌ها"],
        ["icons", "آیکون‌ها"],
        ["patterns", "الگوها"],
    ];
    const RASTER_LONG_SIDE = 1024;

    function init() {
        const trigger = document.querySelector("[data-designs-tool]");
        const root = document.getElementById("customizer");
        const templates = window.BabaeiDesignTemplates || [];
        if (!trigger || !root || !templates.length || trigger.dataset.bound === "1") return;
        trigger.dataset.bound = "1";

        const artworkCache = new Map();
        let overlay = null;
        let activeCategory = "all";
        let busy = false;

        const svgUrl = svg => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
        const csrfToken = () =>
            (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] ||
            root.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

        function setStatus(message, tone) {
            const node = overlay?.querySelector(".designs-status");
            if (!node) return;
            node.textContent = message || "";
            node.dataset.tone = tone || "";
        }

        function renderGrid() {
            const grid = overlay.querySelector(".designs-grid");
            grid.innerHTML = "";
            templates
                .filter(item => activeCategory === "all" || item.category === activeCategory)
                .forEach(item => {
                    const card = document.createElement("button");
                    card.type = "button";
                    card.className = "designs-card";
                    card.dataset.templateId = item.id;
                    card.setAttribute("aria-label", "افزودن طرح " + item.name);

                    const preview = document.createElement("span");
                    preview.className = "designs-card__preview";
                    const image = document.createElement("img");
                    image.alt = "";
                    image.loading = "lazy";
                    image.decoding = "async";
                    image.src = svgUrl(item.svg);
                    // Keep real proportions: wide texts stay wide, icons stay square.
                    image.style.aspectRatio = item.width + " / " + item.height;
                    preview.appendChild(image);

                    const name = document.createElement("span");
                    name.className = "designs-card__name";
                    name.textContent = item.name;

                    const badge = document.createElement("span");
                    badge.className = "designs-card__badge";
                    badge.setAttribute("aria-hidden", "true");

                    card.append(preview, name, badge);
                    card.addEventListener("click", () => addTemplate(item, card));
                    grid.appendChild(card);
                });
        }

        function renderChips() {
            const bar = overlay.querySelector(".designs-chips");
            bar.innerHTML = "";
            CATEGORIES.forEach(([key, label]) => {
                const chip = document.createElement("button");
                chip.type = "button";
                chip.className = "designs-chip" + (key === activeCategory ? " is-active" : "");
                chip.textContent = label;
                chip.setAttribute("aria-pressed", String(key === activeCategory));
                chip.addEventListener("click", () => {
                    activeCategory = key;
                    renderChips();
                    renderGrid();
                    overlay.querySelector(".designs-body").scrollTop = 0;
                });
                bar.appendChild(chip);
            });
        }

        function build() {
            overlay = document.createElement("div");
            overlay.className = "designs-overlay";
            overlay.hidden = true;
            overlay.innerHTML = `
                <section class="designs-dialog" role="dialog" aria-labelledby="designs-title" dir="rtl">
                    <header class="designs-header">
                        <h2 id="designs-title">طرح‌ها</h2>
                        <button type="button" class="designs-close" aria-label="بستن">
                            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                        </button>
                    </header>
                    <div class="designs-body">
                        <p class="designs-section-title">قالب‌ها</p>
                        <div class="designs-chips" role="group" aria-label="دسته‌بندی قالب‌ها"></div>
                        <div class="designs-grid"></div>
                        <p class="designs-more">قالب‌های بیشتر به‌زودی اضافه می‌شود</p>
                    </div>
                    <div class="designs-status" role="status" aria-live="polite"></div>
                </section>`;
            document.body.appendChild(overlay);
            overlay.querySelector(".designs-close").addEventListener("click", close);
            renderChips();
            renderGrid();
        }

        function positionDialog() {
            const panel = document.getElementById("studio-layers-panel");
            const rect = panel?.getBoundingClientRect();
            const rightOffset = rect && rect.width > 0 && rect.left > window.innerWidth * 0.4
                ? window.innerWidth - rect.left + 16
                : 16;
            overlay.style.setProperty("--designs-right", rightOffset + "px");
            const toolbar = document.getElementById("studio-bottom-toolbar");
            const toolbarRect = toolbar?.getBoundingClientRect();
            const bottomOffset = toolbarRect && toolbarRect.height > 0
                ? window.innerHeight - toolbarRect.top + 12
                : 96;
            overlay.style.setProperty("--designs-bottom", bottomOffset + "px");
        }

        function open() {
            if (!overlay) build();
            positionDialog();
            overlay.hidden = false;
            trigger.classList.add("is-active");
            trigger.setAttribute("aria-expanded", "true");
            setStatus("");
            overlay.querySelector(".designs-close").focus({ preventScroll: true });
        }

        function close() {
            if (!overlay) return;
            overlay.hidden = true;
            trigger.classList.remove("is-active");
            trigger.setAttribute("aria-expanded", "false");
            trigger.focus({ preventScroll: true });
        }

        async function rasterize(item) {
            const image = new Image();
            image.decoding = "async";
            const loaded = new Promise((resolve, reject) => {
                image.onload = resolve;
                image.onerror = () => reject(new Error("بارگذاری طرح ناموفق بود."));
            });
            image.src = svgUrl(item.svg);
            await loaded;

            const scale = RASTER_LONG_SIDE / Math.max(item.width, item.height);
            const canvas = document.createElement("canvas");
            canvas.width = Math.round(item.width * scale);
            canvas.height = Math.round(item.height * scale);
            canvas.getContext("2d").drawImage(image, 0, 0, canvas.width, canvas.height);
            const blob = await new Promise(resolve => canvas.toBlob(resolve, "image/png"));
            if (!blob) throw new Error("ساخت تصویر طرح ناموفق بود.");
            return blob;
        }

        async function waitForArtwork(statusUrl) {
            for (let attempt = 0; attempt < 30; attempt += 1) {
                const response = await fetch(statusUrl, { credentials: "same-origin" });
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "وضعیت طرح دریافت نشد.");
                if (result.status === "ready" && result.artwork) return result.artwork;
                if (result.status === "failed") throw new Error(result.error || "پردازش طرح ناموفق بود.");
                await sleep(1000);
            }
            throw new Error("پردازش طرح بیش از حد طول کشید.");
        }

        async function ensureArtwork(item) {
            if (artworkCache.has(item.id)) return artworkCache.get(item.id);

            const blob = await rasterize(item);
            const form = new FormData();
            form.append("image", new File([blob], item.id + ".png", { type: "image/png" }));
            form.append("remove_background", "0");

            const response = await fetch(root.dataset.uploadUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken() },
                credentials: "same-origin",
                body: form,
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "افزودن طرح انجام نشد.");

            const artwork = result.artwork || (
                result.status === "processing" ? await waitForArtwork(result.status_url) : null
            );
            if (!artwork) throw new Error("نتیجه‌ی آپلود طرح نامعتبر است.");

            artwork.name = item.name;
            artwork.is_uploaded = true;
            artworkCache.set(item.id, artwork);
            return artwork;
        }

        async function addTemplate(item, card) {
            if (busy) return;
            const studio = window.BabaeiCustomizer3D;
            if (!studio?.isReady?.()) {
                setStatus("مدل سه‌بعدی هنوز آماده نیست؛ چند لحظه بعد دوباره امتحان کن.", "error");
                return;
            }

            busy = true;
            overlay.classList.add("is-busy");
            card.classList.add("is-loading");
            setStatus("در حال افزودن «" + item.name + "»…");
            try {
                const artwork = await ensureArtwork(item);
                studio.addArtwork(artwork);
                card.classList.add("is-added");
                setTimeout(() => card.classList.remove("is-added"), 1600);
                setStatus("«" + item.name + "» به طراحی اضافه شد.", "ok");
            } catch (error) {
                console.error("[BABAEI][DESIGNS]", error);
                setStatus(error.message || "افزودن طرح انجام نشد.", "error");
            } finally {
                busy = false;
                overlay.classList.remove("is-busy");
                card.classList.remove("is-loading");
            }
        }

        trigger.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            if (overlay && !overlay.hidden) close();
            else open();
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && overlay && !overlay.hidden) close();
        });
        window.addEventListener("resize", () => {
            if (overlay && !overlay.hidden) positionDialog();
        });
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
