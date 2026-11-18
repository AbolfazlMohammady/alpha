/*
 * Library dialogs opened from the bottom toolbar:
 *  - "طرح‌ها" (Designs): built-in templates (text, badges, icons, patterns).
 *  - "لیبل‌ها" (Labels): the label library + the customer's own uploads.
 * Both share one look. Picking a card adds it to the garment as a normal layer,
 * so saving, pricing and ordering work exactly as before.
 */
(() => {
    "use strict";

    const DESIGN_FILTERS = [
        ["all", "همه"],
        ["text", "متن"],
        ["badges", "نشان‌ها"],
        ["icons", "آیکون‌ها"],
        ["patterns", "الگوها"],
    ];
    const LABEL_FILTERS = [
        ["all", "همه"],
        ["mine", "لیبل‌های من"],
        ["library", "کتابخانه"],
    ];
    const RASTER_LONG_SIDE = 1024;
    const PLUS_ICON = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

    function init() {
        const root = document.getElementById("customizer");
        const designsTrigger = document.querySelector("[data-designs-tool]");
        const labelTrigger = document.querySelector('#desktop-tool-dock [data-desktop-tool="label"]');
        if (!root || (!designsTrigger && !labelTrigger) || root.dataset.libraryDialogsBound === "1") return;
        root.dataset.libraryDialogsBound = "1";

        let designData = {};
        try {
            designData = JSON.parse(document.getElementById("designer-data")?.textContent || "{}");
        } catch (error) {
            designData = {};
        }

        const svgUrl = svg => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
        const csrfToken = () =>
            (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] ||
            root.querySelector("input[name=csrfmiddlewaretoken]")?.value || "";
        const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
        const formatPrice = value => Number(value || 0).toLocaleString("fa-IR");
        const el = (tag, className, text) => {
            const node = document.createElement(tag);
            if (className) node.className = className;
            if (text != null) node.textContent = text;
            return node;
        };

        let current = null;
        const dialogs = [];

        // ------------------------------------------------------------ dialog shell
        function createDialog({ title, sectionTitle, filters, trigger, onRender }) {
            const dialog = { overlay: null, trigger, filter: "all", busy: false };

            const setStatus = (message, tone) => {
                const node = dialog.overlay?.querySelector(".designs-status");
                if (!node) return;
                node.textContent = message || "";
                node.dataset.tone = tone || "";
            };

            function renderChips() {
                const bar = dialog.overlay.querySelector(".designs-chips");
                bar.innerHTML = "";
                filters.forEach(([key, label]) => {
                    const chip = el("button", "designs-chip" + (key === dialog.filter ? " is-active" : ""), label);
                    chip.type = "button";
                    chip.setAttribute("aria-pressed", String(key === dialog.filter));
                    chip.addEventListener("click", () => {
                        dialog.filter = key;
                        renderChips();
                        dialog.render();
                        dialog.overlay.querySelector(".designs-body").scrollTop = 0;
                    });
                    bar.appendChild(chip);
                });
            }

            function position() {
                const panel = document.getElementById("studio-layers-panel");
                const rect = panel?.getBoundingClientRect();
                const right = rect && rect.width > 0 && rect.left > window.innerWidth * 0.4
                    ? window.innerWidth - rect.left + 16
                    : 16;
                const toolbarRect = document.getElementById("studio-bottom-toolbar")?.getBoundingClientRect();
                const bottom = toolbarRect && toolbarRect.height > 0
                    ? window.innerHeight - toolbarRect.top + 12
                    : 96;
                dialog.overlay.style.setProperty("--designs-right", right + "px");
                dialog.overlay.style.setProperty("--designs-bottom", bottom + "px");
            }

            function build() {
                const overlay = el("div", "designs-overlay");
                overlay.hidden = true;
                overlay.innerHTML = `
                    <section class="designs-dialog" role="dialog" aria-label="${title}" dir="rtl">
                        <header class="designs-header">
                            <h2>${title}</h2>
                            <button type="button" class="designs-close" aria-label="بستن">
                                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="m6 6 12 12M18 6 6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
                            </button>
                        </header>
                        <div class="designs-body">
                            <p class="designs-section-title">${sectionTitle}</p>
                            <div class="designs-chips" role="group" aria-label="دسته‌بندی"></div>
                            <div class="designs-extra"></div>
                            <div class="designs-grid"></div>
                            <p class="designs-more"></p>
                        </div>
                        <div class="designs-status" role="status" aria-live="polite"></div>
                    </section>`;
                document.body.appendChild(overlay);
                dialog.overlay = overlay;
                dialog.grid = overlay.querySelector(".designs-grid");
                dialog.extra = overlay.querySelector(".designs-extra");
                dialog.more = overlay.querySelector(".designs-more");
                overlay.querySelector(".designs-close").addEventListener("click", () => dialog.close());
                renderChips();
            }

            dialog.setStatus = setStatus;
            dialog.render = () => onRender(dialog);
            dialog.isOpen = () => Boolean(dialog.overlay && !dialog.overlay.hidden);
            dialog.open = () => {
                if (current && current !== dialog) current.close(true);
                if (!dialog.overlay) {
                    build();
                    dialog.render();
                }
                position();
                dialog.overlay.hidden = false;
                trigger?.classList.add("is-active");
                trigger?.setAttribute("aria-expanded", "true");
                setStatus("");
                current = dialog;
                dialog.overlay.querySelector(".designs-close").focus({ preventScroll: true });
            };
            dialog.close = skipFocus => {
                if (!dialog.overlay) return;
                dialog.overlay.hidden = true;
                trigger?.classList.remove("is-active");
                trigger?.setAttribute("aria-expanded", "false");
                if (current === dialog) current = null;
                if (!skipFocus) trigger?.focus({ preventScroll: true });
            };
            dialog.toggle = () => (dialog.isOpen() ? dialog.close() : dialog.open());
            dialog.reposition = () => { if (dialog.isOpen()) position(); };
            dialogs.push(dialog);
            return dialog;
        }

        // ------------------------------------------------------------ shared pieces
        function addToGarment(dialog, artwork, card, label) {
            const studio = window.BabaeiCustomizer3D;
            if (!studio?.isReady?.()) {
                dialog.setStatus("مدل سه‌بعدی هنوز آماده نیست؛ چند لحظه بعد دوباره امتحان کن.", "error");
                return false;
            }
            studio.addArtwork(artwork);
            card?.classList.add("is-added");
            setTimeout(() => card?.classList.remove("is-added"), 1600);
            dialog.setStatus("«" + label + "» به طراحی اضافه شد.", "ok");
            return true;
        }

        function appendBadge(card) {
            const badge = el("span", "designs-card__badge");
            badge.setAttribute("aria-hidden", "true");
            card.appendChild(badge);
        }

        async function waitForArtwork(statusUrl, attempts = 240) {
            for (let attempt = 0; attempt < attempts; attempt += 1) {
                const response = await fetch(statusUrl, { credentials: "same-origin" });
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "وضعیت تصویر دریافت نشد.");
                if (result.status === "ready" && result.artwork) return result.artwork;
                if (result.status === "failed") throw new Error(result.error || "پردازش تصویر ناموفق بود.");
                await sleep(2000);
            }
            throw new Error("پردازش تصویر بیش از حد طول کشید.");
        }

        async function uploadFile(file, removeBackground) {
            const form = new FormData();
            form.append("image", file);
            form.append("remove_background", removeBackground ? "1" : "0");
            const response = await fetch(root.dataset.uploadUrl, {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken() },
                credentials: "same-origin",
                body: form,
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "آپلود انجام نشد.");
            const artwork = result.artwork || (
                result.status === "processing" ? await waitForArtwork(result.status_url) : null
            );
            if (!artwork) throw new Error("نتیجه‌ی آپلود نامعتبر است.");
            artwork.is_uploaded = true;
            return artwork;
        }

        // ------------------------------------------------------------ Designs (templates)
        const templates = window.BabaeiDesignTemplates || [];
        const templateArtworks = new Map();

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

        async function ensureTemplateArtwork(item) {
            if (templateArtworks.has(item.id)) return templateArtworks.get(item.id);
            const blob = await rasterize(item);
            const artwork = await uploadFile(new File([blob], item.id + ".png", { type: "image/png" }), false);
            artwork.name = item.name;
            templateArtworks.set(item.id, artwork);
            return artwork;
        }

        async function addTemplate(dialog, item, card) {
            if (dialog.busy) return;
            if (!window.BabaeiCustomizer3D?.isReady?.()) {
                dialog.setStatus("مدل سه‌بعدی هنوز آماده نیست؛ چند لحظه بعد دوباره امتحان کن.", "error");
                return;
            }
            dialog.busy = true;
            dialog.overlay.classList.add("is-busy");
            card.classList.add("is-loading");
            dialog.setStatus("در حال افزودن «" + item.name + "»…");
            try {
                const artwork = await ensureTemplateArtwork(item);
                addToGarment(dialog, artwork, card, item.name);
            } catch (error) {
                console.error("[BABAEI][DESIGNS]", error);
                dialog.setStatus(error.message || "افزودن طرح انجام نشد.", "error");
            } finally {
                dialog.busy = false;
                dialog.overlay.classList.remove("is-busy");
                card.classList.remove("is-loading");
            }
        }

        function renderDesignGrid(dialog) {
            dialog.more.textContent = "قالب‌های بیشتر به‌زودی اضافه می‌شود";
            dialog.grid.innerHTML = "";
            templates
                .filter(item => dialog.filter === "all" || item.category === dialog.filter)
                .forEach(item => {
                    const card = el("button", "designs-card");
                    card.type = "button";
                    card.dataset.templateId = item.id;
                    card.setAttribute("aria-label", "افزودن طرح " + item.name);

                    const preview = el("span", "designs-card__preview");
                    const image = document.createElement("img");
                    image.alt = "";
                    image.loading = "lazy";
                    image.decoding = "async";
                    image.src = svgUrl(item.svg);
                    image.style.aspectRatio = item.width + " / " + item.height;
                    preview.appendChild(image);

                    card.append(preview, el("span", "designs-card__name", item.name));
                    appendBadge(card);
                    card.addEventListener("click", () => addTemplate(dialog, item, card));
                    dialog.grid.appendChild(card);
                });
        }

        // ------------------------------------------------------------ Labels (library + uploads)
        const labelArtworks = [...(designData.artworks || [])];
        const prices = designData.prices || {};
        let removeBackground = false;
        let fileInput = null;

        function artworkPrice(artwork) {
            const prefix = artwork.id + ":";
            const key = Object.keys(prices).find(item => item.startsWith(prefix));
            return Number(key ? prices[key] : artwork.base_price || 0);
        }

        function renderLabelGrid(dialog) {
            dialog.more.textContent = "";
            dialog.grid.innerHTML = "";

            if (!dialog.extra.childElementCount) {
                const option = el("label", "designs-option");
                const checkbox = document.createElement("input");
                checkbox.type = "checkbox";
                checkbox.addEventListener("change", () => { removeBackground = checkbox.checked; });
                option.append(checkbox, el("span", "", "حذف پس‌زمینه‌ی عکس هنگام آپلود"));
                dialog.extra.appendChild(option);

                fileInput = document.createElement("input");
                fileInput.type = "file";
                fileInput.accept = "image/png,image/jpeg,image/webp";
                fileInput.hidden = true;
                fileInput.addEventListener("change", () => handleUpload(dialog));
                dialog.extra.appendChild(fileInput);
            }

            const upload = el("button", "designs-card designs-card--upload");
            upload.type = "button";
            upload.setAttribute("aria-label", "آپلود لیبل جدید");
            const plus = el("span", "designs-card__plus");
            plus.innerHTML = PLUS_ICON;
            upload.append(plus, el("span", "designs-card__name", "آپلود لیبل جدید"), el("small", "designs-card__hint", "PNG ، JPG یا WEBP"));
            upload.addEventListener("click", () => {
                if (dialog.busy) return;
                fileInput.value = "";
                fileInput.click();
            });
            dialog.grid.appendChild(upload);
            dialog.uploadCard = upload;

            const visible = labelArtworks.filter(item => {
                if (dialog.filter === "mine") return item.is_uploaded;
                if (dialog.filter === "library") return !item.is_uploaded;
                return true;
            });
            visible.forEach(artwork => {
                const card = el("button", "designs-card");
                card.type = "button";
                card.dataset.artworkId = artwork.id;
                card.setAttribute("aria-label", "افزودن لیبل " + artwork.name);

                const preview = el("span", "designs-card__preview");
                const image = document.createElement("img");
                image.alt = "";
                image.loading = "lazy";
                image.decoding = "async";
                image.src = artwork.image;
                preview.appendChild(image);

                const price = artworkPrice(artwork);
                const caption = el("span", "designs-card__name", artwork.name);
                const meta = el("small", "designs-card__hint",
                    (artwork.is_uploaded ? "لیبل من" : (artwork.code || "لیبل")) +
                    (price > 0 ? " · " + formatPrice(price) + " تومان" : ""));
                card.append(preview, caption, meta);
                appendBadge(card);
                card.addEventListener("click", () => addToGarment(dialog, artwork, card, artwork.name));
                dialog.grid.appendChild(card);
            });

            if (dialog.filter === "mine" && !visible.length) {
                dialog.more.textContent = "هنوز لیبلی آپلود نکرده‌ای. با کارت «آپلود لیبل جدید» شروع کن.";
            }
        }

        async function handleUpload(dialog) {
            const file = fileInput?.files?.[0];
            if (!file || dialog.busy) return;
            dialog.busy = true;
            dialog.overlay.classList.add("is-busy");
            dialog.uploadCard?.classList.add("is-loading");
            dialog.setStatus(removeBackground
                ? "تصویر دریافت شد؛ حذف هوشمند پس‌زمینه ممکن است کمی طول بکشد…"
                : "در حال آپلود تصویر…");
            try {
                const artwork = await uploadFile(file, removeBackground);
                labelArtworks.unshift(artwork);
                dialog.filter = "mine";
                dialog.overlay.querySelector(".designs-chips").querySelectorAll(".designs-chip").forEach((chip, index) => {
                    const active = LABEL_FILTERS[index][0] === "mine";
                    chip.classList.toggle("is-active", active);
                    chip.setAttribute("aria-pressed", String(active));
                });
                dialog.setStatus("تصویر آپلود شد و به لیبل‌های من اضافه شد؛ برای قرار دادن روی لباس رویش بزن.", "ok");
                // Mirror the original behaviour: uploading only adds to the library.
                document.dispatchEvent(new CustomEvent("babaei:artwork-uploaded", { detail: { artwork } }));
            } catch (error) {
                console.error("[BABAEI][LABELS]", error);
                dialog.setStatus(error.message || "آپلود انجام نشد.", "error");
            } finally {
                dialog.busy = false;
                dialog.overlay.classList.remove("is-busy");
                fileInput.value = "";
                renderLabelGrid(dialog);
            }
        }

        // ------------------------------------------------------------ wiring
        if (designsTrigger && templates.length) {
            const designsDialog = createDialog({
                title: "طرح‌ها",
                sectionTitle: "قالب‌ها",
                filters: DESIGN_FILTERS,
                trigger: designsTrigger,
                onRender: renderDesignGrid,
            });
            designsTrigger.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                designsDialog.toggle();
            });
        }

        if (labelTrigger) {
            const labelsDialog = createDialog({
                title: "لیبل‌ها",
                sectionTitle: "لیبل‌های من و کتابخانه",
                filters: LABEL_FILTERS,
                trigger: labelTrigger,
                onRender: renderLabelGrid,
            });
            // Capture phase: replace the old label popover with this dialog.
            labelTrigger.addEventListener("click", event => {
                event.preventDefault();
                event.stopImmediatePropagation();
                labelsDialog.toggle();
            }, true);
        }

        // Opening any other dock tool closes the library dialogs.
        document.querySelectorAll('#desktop-tool-dock [data-desktop-tool]').forEach(button => {
            if (button === labelTrigger) return;
            button.addEventListener("click", () => { if (current) current.close(true); });
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && current) current.close();
        });
        window.addEventListener("resize", () => dialogs.forEach(dialog => dialog.reposition()));
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
