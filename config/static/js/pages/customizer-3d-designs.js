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
        ["persian", "ایرانی"],
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
    const PRODUCT_ART = {"tshirt":"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 110\" fill=\"#f1f1f4\" stroke=\"#1d1d1f\" stroke-width=\"3\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><path d=\"M44 10 L20 22 L6 44 L24 54 L31 43 L31 100 L89 100 L89 43 L96 54 L114 44 L100 22 L76 10 C72 20 66 24 60 24 C54 24 48 20 44 10 Z\"/><path d=\"M44 10 C48 20 54 24 60 24 C66 24 72 20 76 10\" fill=\"none\" stroke-width=\"2\"/></svg>","long_sleeve":"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 110\" fill=\"#f1f1f4\" stroke=\"#1d1d1f\" stroke-width=\"3\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><path d=\"M44 10 L22 20 L5 84 L19 90 L34 46 L34 100 L86 100 L86 46 L101 90 L115 84 L98 20 L76 10 C72 20 66 24 60 24 C54 24 48 20 44 10 Z\"/><path d=\"M5 84 L19 90 M101 90 L115 84\" stroke-width=\"5\"/></svg>","hoodie":"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 110\" fill=\"#f1f1f4\" stroke=\"#1d1d1f\" stroke-width=\"3\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><path d=\"M40 16 L20 26 L5 84 L19 90 L34 50 L34 102 L86 102 L86 50 L101 90 L115 84 L100 26 L80 16 Z\"/><path d=\"M40 16 C36 -2 84 -2 80 16 C74 26 66 30 60 30 C54 30 46 26 40 16 Z\"/><path d=\"M42 78 H78 L84 98 H36 Z\" fill=\"none\"/><path d=\"M54 30 V48 M66 30 V48\" stroke-width=\"2.5\"/></svg>","mug":"<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 120 110\" fill=\"#f1f1f4\" stroke=\"#1d1d1f\" stroke-width=\"3\" stroke-linejoin=\"round\" stroke-linecap=\"round\"><path d=\"M28 24 H84 V80 C84 94 74 102 56 102 C38 102 28 94 28 80 Z\"/><ellipse cx=\"56\" cy=\"24\" rx=\"28\" ry=\"6\"/><path d=\"M84 38 H94 C108 38 108 68 94 68 H84\" fill=\"none\"/></svg>"};
    const PLUS_ICON = '<svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';

    function init() {
        const root = document.getElementById("customizer");
        const designsTrigger = document.querySelector("[data-designs-tool]");
        const labelTrigger = document.querySelector('#desktop-tool-dock [data-desktop-tool="label"]');
        if (!root || root.dataset.libraryDialogsBound === "1") return;
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
        function createDialog({ title, sectionTitle, filters, trigger, onRender, getTitle, kind }) {
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
                if (!filters.length) return;
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
                            <h2>${getTitle ? getTitle() : title}</h2>
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
                if (kind) dialog.grid.dataset.kind = kind;
                dialog.extra = overlay.querySelector(".designs-extra");
                dialog.more = overlay.querySelector(".designs-more");
                overlay.querySelector(".designs-close").addEventListener("click", () => dialog.close());
                renderChips();
            }

            dialog.setStatus = setStatus;
            dialog.render = () => onRender(dialog);
            dialog.isOpen = () => Boolean(dialog.overlay && !dialog.overlay.hidden);
            dialog.open = () => {
                if (window.BabaeiCustomizer3D?.isTurntable?.()) window.BabaeiCustomizer3D.setTurntable(false);
                if (current && current !== dialog) current.close(true);
                if (!dialog.overlay) {
                    build();
                    dialog.render();
                } else if (kind) {
                    dialog.render();   // product / colour lists reflect the live state
                }
                if (getTitle) dialog.overlay.querySelector(".designs-header h2").textContent = getTitle();
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

        // ------------------------------------------------------------ Product picker
        const garmentRegistry = () => Array.from(
            document.querySelectorAll("#garment-model-registry [data-garment-type][data-model-url]")
        );

        function currentGarment() {
            return window.BabaeiCustomizer3D?.getGarmentType?.() || "tshirt";
        }

        function garmentLabel(type) {
            const source = garmentRegistry().find(item => item.dataset.garmentType === type);
            return source?.dataset.garmentLabel || "محصول";
        }

        function renderProductGrid(dialog) {
            dialog.more.textContent = "";
            dialog.grid.innerHTML = "";
            const active = currentGarment();
            garmentRegistry().forEach(source => {
                const type = source.dataset.garmentType || "";
                const card = el("button", "designs-card designs-card--product" + (type === active ? " is-selected" : ""));
                card.type = "button";
                card.dataset.garmentType = type;
                card.setAttribute("aria-pressed", String(type === active));

                const preview = el("span", "designs-card__preview");
                preview.innerHTML = PRODUCT_ART[type] || PRODUCT_ART.tshirt;
                card.append(
                    preview,
                    el("span", "designs-card__name designs-card__name--strong", source.dataset.garmentLabel || type),
                    el("small", "designs-card__hint", source.dataset.garmentSubtitle || ""),
                );
                const mark = el("span", "designs-card__selected");
                mark.setAttribute("aria-hidden", "true");
                card.appendChild(mark);

                card.addEventListener("click", async () => {
                    if (dialog.busy || type === currentGarment()) return;
                    const studio = window.BabaeiCustomizer3D;
                    if (!studio?.setGarmentType) return;
                    dialog.busy = true;
                    dialog.overlay.classList.add("is-busy");
                    card.classList.add("is-loading");
                    dialog.setStatus("در حال آماده‌سازی «" + (source.dataset.garmentLabel || type) + "»…");
                    try {
                        const changed = await studio.setGarmentType(type);
                        if (changed) {
                            dialog.render();
                            dialog.setStatus("");
                            setTimeout(() => dialog.close(true), 250);
                        }
                    } catch (error) {
                        console.error("[BABAEI][PRODUCT]", error);
                        dialog.setStatus("تغییر محصول انجام نشد.", "error");
                    } finally {
                        dialog.busy = false;
                        dialog.overlay.classList.remove("is-busy");
                        card.classList.remove("is-loading");
                    }
                });
                dialog.grid.appendChild(card);
            });
        }

        // ------------------------------------------------------------ Colour picker
        function renderColorGrid(dialog) {
            dialog.more.textContent = "";
            dialog.grid.innerHTML = "";
            const sources = Array.from(document.querySelectorAll("#variant-color-list-right button[data-color]"));
            if (!sources.length) {
                dialog.more.textContent = "رنگی برای این محصول تعریف نشده است.";
                return;
            }
            sources.forEach(source => {
                const name = source.dataset.color || "";
                const hex = source.style.getPropertyValue("--swatch") || "#ffffff";
                const selected = source.classList.contains("is-active");
                const card = el("button", "designs-card designs-card--color" + (selected ? " is-selected" : ""));
                card.type = "button";
                card.dataset.color = name;
                card.setAttribute("aria-pressed", String(selected));
                card.setAttribute("aria-label", "رنگ " + name);

                const preview = el("span", "designs-card__preview");
                const swatch = el("span", "designs-swatch");
                swatch.style.background = hex;
                preview.appendChild(swatch);
                card.append(preview, el("span", "designs-card__name designs-card__name--strong", name));
                const mark = el("span", "designs-card__selected");
                mark.setAttribute("aria-hidden", "true");
                card.appendChild(mark);

                card.addEventListener("click", () => {
                    // Go through the real variant button so price, stock and the
                    // 3D material all stay in sync (see studio-ui chooseVariant).
                    source.click();
                    dialog.grid.querySelectorAll(".designs-card").forEach(item => {
                        const active = item === card;
                        item.classList.toggle("is-selected", active);
                        item.setAttribute("aria-pressed", String(active));
                    });
                    dialog.setStatus("رنگ «" + name + "» اعمال شد.", "ok");
                });
                dialog.grid.appendChild(card);
            });
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


        const productTrigger = document.querySelector('#desktop-tool-dock [data-desktop-tool="garment"]');
        if (productTrigger) {
            const productDialog = createDialog({
                title: "انتخاب محصول",
                sectionTitle: "چه محصولی طراحی می‌کنی؟",
                filters: [],
                trigger: productTrigger,
                onRender: renderProductGrid,
                kind: "products",
            });
            productTrigger.addEventListener("click", event => {
                event.preventDefault();
                event.stopImmediatePropagation();
                productDialog.toggle();
            }, true);
        }

        const colorTrigger = document.querySelector('#desktop-tool-dock [data-desktop-tool="shirt-color"]');
        if (colorTrigger) {
            const colorDialog = createDialog({
                title: "رنگ محصول",
                getTitle: () => "رنگ " + garmentLabel(currentGarment()),
                sectionTitle: "رنگ‌های موجود",
                filters: [],
                trigger: colorTrigger,
                onRender: renderColorGrid,
                kind: "colors",
            });
            colorTrigger.addEventListener("click", event => {
                event.preventDefault();
                event.stopImmediatePropagation();
                colorDialog.toggle();
            }, true);
        }

        // 360-degree turntable (the "video" option of the reference editor).
        const turntableTrigger = document.querySelector("[data-turntable-tool]");
        if (turntableTrigger) {
            turntableTrigger.addEventListener("click", () => {
                const studio = window.BabaeiCustomizer3D;
                if (!studio?.setTurntable || !studio.isReady?.()) return;
                const turningOn = !studio.isTurntable();
                if (turningOn) {
                    if (current) current.close(true);
                    // A hidden 3D view can't show the spin, so open it first.
                    const activeView = document.querySelector("#studio-view-switcher .is-active")?.dataset.studioView;
                    if (activeView === "2d") document.querySelector('#studio-view-switcher [data-studio-view="3d"]')?.click();
                }
                studio.setTurntable(turningOn);
            });
            document.addEventListener("babaei:turntable-changed", event => {
                const active = Boolean(event.detail?.active);
                turntableTrigger.classList.toggle("is-active", active);
                turntableTrigger.setAttribute("aria-pressed", String(active));
            });
        }

        // Opening any other dock tool closes the library dialogs.
        const ownedTriggers = new Set([labelTrigger, productTrigger, colorTrigger]);
        document.querySelectorAll('#desktop-tool-dock [data-desktop-tool]').forEach(button => {
            if (ownedTriggers.has(button)) return;
            button.addEventListener("click", () => {
                if (current) current.close(true);
                if (window.BabaeiCustomizer3D?.isTurntable?.()) window.BabaeiCustomizer3D.setTurntable(false);
            });
        });
        document.addEventListener("keydown", event => {
            if (event.key === "Escape" && current) current.close();
        });
        window.addEventListener("resize", () => dialogs.forEach(dialog => dialog.reposition()));
    }

    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
    else init();
})();
