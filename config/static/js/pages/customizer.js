(() => {
    "use strict";

    const root = document.getElementById("customizer");
    if (!root) return;

    const data = JSON.parse(document.getElementById("designer-data")?.textContent || "{}");
    const canvas = document.getElementById("designer-canvas");
    const has3DStudio = Boolean(document.getElementById("designer-3d-stage"));
    const ctx = canvas?.getContext("2d");
    const stage = document.getElementById("stage-shell");
    const loading = document.getElementById("stage-loading");
    const viewSwitcher = document.getElementById("view-switcher");
    const artworkGrid = document.getElementById("artwork-grid");
    const areaList = document.getElementById("area-list");
    const selectedCard = document.getElementById("selected-card");
    const priceBreakdown = document.getElementById("price-breakdown");
    const totalEl = document.getElementById("designer-total");
    const variantSelect = document.getElementById("variant-select");
    const vendorListingSelect = document.getElementById("designer-vendor-listing");
    const saveButton = document.getElementById("save-design");
    const saveStatus = document.getElementById("save-status");
    const uploadInput = document.getElementById("artwork-upload");
    const uploadStatus = document.getElementById("upload-status");
    const removeBackgroundInput = document.getElementById("artwork-remove-background");
    const processingOverlay = document.getElementById("artwork-processing-overlay");
    const setProcessingState = (processing) => {
        if (!processingOverlay) return;
        processingOverlay.hidden = !processing;
        processingOverlay.setAttribute("aria-hidden", String(!processing));
        document.body.classList.toggle("artwork-processing-active", processing);
        if (uploadInput) uploadInput.disabled = processing;
    };
    const selectedControls = document.getElementById("selected-controls");
    const zoomLabel = document.getElementById("zoom-label");

    const views = data.views || [];
    const artworks = data.artworks || [];
    const prices = data.prices || {};
    const variants = data.variants || [];
    const basePrice = Number(data.base_price || 0);
    const imageCache = new Map();
    const layers = [];

    let activeViewIndex = 0;
    let activeAreaId = null;
    let selectedLayerId = null;
    let stageZoom = 1;
    let nextLayerId = 1;
    let dragState = null;
    let renderToken = 0;

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
    const formatPrice = (value) => Number(value || 0).toLocaleString("fa-IR");
    const activeView = () => views[activeViewIndex] || null;
    const artworkById = (id) => artworks.find((item) => Number(item.id) === Number(id));
    const areaById = (id, view = activeView()) => view?.areas?.find((area) => Number(area.id) === Number(id)) || null;

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>\'\"]/g, (char) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
        }[char]));
    }

    function getCookie(name) {
        for (const cookie of (document.cookie || "").split(";")) {
            const [key, ...value] = cookie.trim().split("=");
            if (key === name) return decodeURIComponent(value.join("="));
        }
        return "";
    }

    function loadImage(src) {
        if (imageCache.has(src)) return imageCache.get(src);
        const image = new Image();
        image.decoding = "async";
        const promise = new Promise((resolve, reject) => {
            image.onload = () => resolve(image);
            image.onerror = reject;
        });
        image.src = src;
        imageCache.set(src, promise);
        return promise;
    }

    function polygonPoints(geometry) {
        return (geometry || []).map((p) => ({ x: Number(p.x), y: Number(p.y) }));
    }

    function areaBounds(area) {
        const points = polygonPoints(area.geometry);
        const xs = points.map((p) => p.x);
        const ys = points.map((p) => p.y);
        return { x: Math.min(...xs), y: Math.min(...ys), width: Math.max(...xs) - Math.min(...xs), height: Math.max(...ys) - Math.min(...ys) };
    }

    function rotatePoint(point, center, radians) {
        const cos = Math.cos(radians), sin = Math.sin(radians);
        const x = point.x - center.x, y = point.y - center.y;
        return { x: center.x + x * cos - y * sin, y: center.y + x * sin + y * cos };
    }

    function layerCorners(layer, area) {
        const bounds = areaBounds(area);
        const center = { x: bounds.x + layer.x * bounds.width, y: bounds.y + layer.y * bounds.height };
        const width = layer.width * bounds.width, height = layer.height * bounds.height;
        const corners = [
            { x: center.x - width / 2, y: center.y - height / 2 },
            { x: center.x + width / 2, y: center.y - height / 2 },
            { x: center.x + width / 2, y: center.y + height / 2 },
            { x: center.x - width / 2, y: center.y + height / 2 },
        ];
        return corners.map((point) => rotatePoint(point, center, layer.rotation * Math.PI / 180));
    }

    function cross(a, b, c) {
        return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
    }

    function pointOnSegment(a, b, point) {
        return Math.abs(cross(a, b, point)) < 1e-7
            && point.x >= Math.min(a.x, b.x) - 1e-7 && point.x <= Math.max(a.x, b.x) + 1e-7
            && point.y >= Math.min(a.y, b.y) - 1e-7 && point.y <= Math.max(a.y, b.y) + 1e-7;
    }

    function pointInPolygon(point, polygon) {
        if (polygon.some((p, i) => pointOnSegment(polygon[i - 1] || polygon[polygon.length - 1], p, point))) return true;
        let inside = false;
        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const a = polygon[i], b = polygon[j];
            if ((a.y > point.y) !== (b.y > point.y)) {
                const x = (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x;
                if (point.x < x) inside = !inside;
            }
        }
        return inside;
    }

    function properIntersection(a, b, c, d) {
        const abC = cross(a, b, c), abD = cross(a, b, d), cdA = cross(c, d, a), cdB = cross(c, d, b);
        return ((abC > 1e-7 && abD < -1e-7) || (abC < -1e-7 && abD > 1e-7))
            && ((cdA > 1e-7 && cdB < -1e-7) || (cdA < -1e-7 && cdB > 1e-7));
    }

    function rectInsidePolygon(corners, polygon) {
        if (!corners.every((point) => pointInPolygon(point, polygon))) return false;
        for (let i = 0; i < corners.length; i += 1) {
            const a = corners[i], b = corners[(i + 1) % corners.length];
            for (let j = 0; j < polygon.length; j += 1) {
                if (properIntersection(a, b, polygon[j], polygon[(j + 1) % polygon.length])) return false;
            }
        }
        return true;
    }

    function overlap(first, second) {
        const axes = [];
        [first, second].forEach((corners) => {
            for (let i = 0; i < 2; i += 1) {
                const edge = { x: corners[i + 1].x - corners[i].x, y: corners[i + 1].y - corners[i].y };
                const length = Math.hypot(edge.x, edge.y) || 1;
                axes.push({ x: -edge.y / length, y: edge.x / length });
            }
        });
        for (const axis of axes) {
            const project = (points) => points.map((p) => p.x * axis.x + p.y * axis.y);
            const a = project(first), b = project(second);
            if (Math.max(...a) <= Math.min(...b) + 1e-7 || Math.max(...b) <= Math.min(...a) + 1e-7) return false;
        }
        return true;
    }

    function viewsForArea(areaId) {
        return views.filter((view) => view.areas?.some((area) => Number(area.id) === Number(areaId)));
    }

    function isLayerValid(candidate, ignoreId = null) {
        const candidateViews = viewsForArea(candidate.area_id);
        if (!candidateViews.length) return false;
        const sameArea = layers.filter((layer) => Number(layer.area_id) === Number(candidate.area_id) && layer.id !== ignoreId);
        for (const view of candidateViews) {
            const area = areaById(candidate.area_id, view);
            const corners = layerCorners(candidate, area);
            if (!rectInsidePolygon(corners, polygonPoints(area.geometry))) return false;
            for (const other of sameArea) {
                const otherArea = areaById(other.area_id, view);
                if (otherArea && overlap(corners, layerCorners(other, otherArea))) return false;
            }
        }
        return true;
    }

    function renderViews() {
        if (!viewSwitcher) return;
        viewSwitcher.innerHTML = views.map((view, index) => `<button type="button" class="view-button ${index === activeViewIndex ? "is-active" : ""}" data-view-index="${index}">${escapeHtml(view.name)}</button>`).join("");
        viewSwitcher.querySelectorAll(".view-button").forEach((button) => button.addEventListener("click", () => {
            activeViewIndex = Number(button.dataset.viewIndex);
            const visible = activeView()?.areas || [];
            if (!visible.some((area) => Number(area.id) === Number(activeAreaId))) activeAreaId = visible[0]?.id || null;
            selectedLayerId = null;
            renderAll();
        }));
    }

    function renderArtworks() {
        const activeArea = areaById(activeAreaId);
        const libraryArtworks = artworks.filter((artwork) => !artwork.is_uploaded);
        const uploadedArtworks = artworks.filter((artwork) => artwork.is_uploaded);

        const renderArtworkCard = (artwork) => {
            const key = activeArea ? `${artwork.id}:${activeArea.id}` : "";
            const areaPrice = key && Object.prototype.hasOwnProperty.call(prices, key)
                ? Number(prices[key])
                : Number(artwork.base_price || 0);
            return `<button type="button" class="artwork-card ${artwork.is_uploaded ? "artwork-card--uploaded" : ""}" data-artwork-id="${artwork.id}">
                <span class="artwork-card__visual"><img src="${escapeHtml(artwork.image)}" alt="" loading="lazy"></span>
                <span class="artwork-card__info">
                    <strong>${escapeHtml(artwork.name)}</strong>
                    <small class="artwork-card__code">${escapeHtml(artwork.is_uploaded ? "لیبل من" : (artwork.code || "LBL"))}</small>
                    <small>${formatPrice(areaPrice)} تومان</small>
                </span>
            </button>`;
        };

        // Keep the personal-label path visible even before the user has uploaded
        // anything. The ready-made library starts collapsed so it never pushes
        // the upload action below a long list of labels.
        // Keep the personal-label section discoverable, but preserve the
        // original direct artwork-grid structure so ready-made label cards keep
        // their established thumbnails/layout.
        artworkGrid.innerHTML = `
            <section class="artwork-library-section artwork-library-section--uploaded artwork-library-section--collapsible" data-artwork-section="uploaded">
                <button type="button" class="artwork-library-section__toggle" aria-expanded="true">
                    <span>لیبل‌های من</span><span class="artwork-library-section__chevron">⌄</span>
                </button>
                <div class="artwork-library-section__grid artwork-grid">
                    ${uploadedArtworks.length
                        ? uploadedArtworks.map(renderArtworkCard).join("")
                        : `<div class="selected-card__empty">هنوز لیبلی اضافه نکردی.</div>`}
                </div>
            </section>
            ${libraryArtworks.length ? `
                <section class="artwork-library-section artwork-library-section--collapsible" data-artwork-section="library">
                    <button type="button" class="artwork-library-section__toggle" aria-expanded="false">
                        <span>کتابخانه لیبل‌ها</span><span class="artwork-library-section__chevron">⌄</span>
                    </button>
                    <div class="artwork-library-section__grid artwork-grid" hidden>
                        ${libraryArtworks.map(renderArtworkCard).join("")}
                    </div>
                </section>` : ""}
        `;
        artworkGrid.querySelectorAll("[data-artwork-section] .artwork-library-section__toggle").forEach((toggle) => {
            toggle.addEventListener("click", () => {
                const section = toggle.closest("[data-artwork-section]");
                const grid = section?.querySelector(".artwork-library-section__grid");
                if (!grid) return;
                const isOpen = !grid.hidden;
                grid.hidden = isOpen;
                toggle.setAttribute("aria-expanded", String(!isOpen));
                section.classList.toggle("is-open", !isOpen);
            });
        });

        artworkGrid.querySelectorAll(".artwork-card").forEach((button) => button.addEventListener("click", () => {
            const artworkId = Number(button.dataset.artworkId);
            if (window.BabaeiCustomizer3D?.isReady?.()) {
                const artwork = artworkById(artworkId);
                if (artwork) window.BabaeiCustomizer3D.addArtwork(artwork);
            } else {
                addLayer(artworkId);
            }

            const library = document.getElementById("label-library-panel");
            const trigger = document.getElementById("label-library-trigger");
            if (library && trigger) {
                library.hidden = true;
                trigger.setAttribute("aria-expanded", "false");
            }
            document.body.classList.remove("label-library-open");
        }));
    }

    function renderAreas() {
        const visibleAreas = activeView()?.areas || [];
        if (!activeAreaId && visibleAreas.length) activeAreaId = visibleAreas[0].id;
        areaList.innerHTML = visibleAreas.map((area) => {
            return `<button type="button" class="area-option ${Number(area.id) === Number(activeAreaId) ? "is-active" : ""}" data-area-id="${area.id}"><span>${escapeHtml(area.name)}</span></button>`;
        }).join("");
        areaList.querySelectorAll(".area-option").forEach((button) => button.addEventListener("click", () => {
            activeAreaId = Number(button.dataset.areaId);
            renderAll();
        }));
    }

    function renderVariants() {
        const current = variantSelect.value;
        variantSelect.innerHTML = `<option value="">انتخاب رنگ و سایز</option>` + variants.map((variant) => `<option value="${variant.id}">${escapeHtml(variant.color)} / ${escapeHtml(variant.size)} — ${formatPrice(variant.price)} تومان${Number(variant.stock) <= 0 ? " — ناموجود" : ""}</option>`).join("");
        if (variants.some((variant) => String(variant.id) === current)) variantSelect.value = current;
    }

    function renderSelection() {
        if (!selectedCard || !selectedControls) return;
        const layer = layers.find((item) => item.id === selectedLayerId);
        if (!layer) {
            selectedCard.innerHTML = `<span class="selected-card__empty">یک لیبل را انتخاب کنید.</span>`;
            selectedControls.hidden = true;
            return;
        }
        const artwork = artworkById(layer.artwork_id), area = areaById(layer.area_id);
        selectedCard.innerHTML = `<div class="selected-card__title">${escapeHtml(artwork?.name || "لیبل")}</div><span class="selected-card__meta">${escapeHtml(area?.name || "ناحیه چاپ")} · ${Math.round(layer.width * 100)}% × ${Math.round(layer.height * 100)}%</span>`;
        selectedControls.hidden = false;
    }

    function layerPrice(layer) {
        const key = `${layer.artwork_id}:${layer.area_id}`;
        return Object.prototype.hasOwnProperty.call(prices, key) ? Number(prices[key]) : Number(artworkById(layer.artwork_id)?.base_price || 0);
    }

    function renderPrices() {
        const variant = variants.find((item) => String(item.id) === String(variantSelect.value));
        const selectedVendorOption = vendorListingSelect && vendorListingSelect.value ? vendorListingSelect.selectedOptions[0] : null;
        const base = selectedVendorOption ? Number(selectedVendorOption.dataset.price || 0) : (variant ? Number(variant.price) : basePrice);
        let total = base;
        const lines = [`<div class="price-line"><span>لباس</span><strong>${formatPrice(base)} تومان</strong></div>`];
        layers.forEach((layer) => {
            const price = layerPrice(layer);
            total += price;
            const artwork = artworkById(layer.artwork_id);
            const area = views.flatMap((view) => view.areas || []).find((item) => Number(item.id) === Number(layer.area_id));
            lines.push(`<div class="price-line"><span>${escapeHtml(artwork?.name || "لیبل")} · ${escapeHtml(area?.name || "ناحیه")}</span><strong>+ ${formatPrice(price)}</strong></div>`);
        });
        priceBreakdown.innerHTML = lines.join("");
        totalEl.textContent = formatPrice(total);
    }

    function canvasSize(view) {
        const width = Math.max(1, Math.min(stage.clientWidth - 20, 640));
        return { width, height: Math.max(1, Math.min(width * view.height / view.width, 610)) };
    }

    function layerCanvasRect(layer, area, view, width, height) {
        const bounds = areaBounds(area);
        return {
            cx: (bounds.x + layer.x * bounds.width) * width,
            cy: (bounds.y + layer.y * bounds.height) * height,
            width: layer.width * bounds.width * width,
            height: layer.height * bounds.height * height,
        };
    }

    async function renderCanvas() {
        const token = ++renderToken;
        const view = activeView();
        if (!view) return;
        const size = canvasSize(view), dpr = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.round(size.width * dpr);
        canvas.height = Math.round(size.height * dpr);
        canvas.style.width = `${size.width}px`;
        canvas.style.height = `${size.height}px`;
        ctx.setTransform(dpr * stageZoom, 0, 0, dpr * stageZoom, 0, 0);
        ctx.clearRect(0, 0, size.width / stageZoom, size.height / stageZoom);
        try {
            const background = await loadImage(view.background);
            if (token !== renderToken) return;
            ctx.drawImage(background, 0, 0, size.width / stageZoom, size.height / stageZoom);
            loading.classList.add("is-hidden");
        } catch {
            loading.textContent = "تصویر نما بارگذاری نشد.";
            loading.classList.remove("is-hidden");
            return;
        }

        for (const area of (view.areas || [])) {
            const polygon = polygonPoints(area.geometry);
            ctx.save();
            ctx.beginPath();
            polygon.forEach((point, index) => index ? ctx.lineTo(point.x * size.width, point.y * size.height) : ctx.moveTo(point.x * size.width, point.y * size.height));
            ctx.closePath();
            ctx.fillStyle = "rgba(255,255,255,.05)";
            ctx.strokeStyle = Number(area.id) === Number(activeAreaId) ? "rgba(23,22,20,.55)" : "rgba(23,22,20,.16)";
            ctx.lineWidth = Number(area.id) === Number(activeAreaId) ? 2 : 1;
            ctx.setLineDash(Number(area.id) === Number(activeAreaId) ? [7, 5] : [4, 5]);
            ctx.fill();
            ctx.stroke();
            ctx.restore();
        }

        const visibleLayers = layers.filter((layer) => (view.areas || []).some((area) => Number(area.id) === Number(layer.area_id)));
        for (const layer of visibleLayers) {
            const area = areaById(layer.area_id, view), artwork = artworkById(layer.artwork_id);
            if (!area || !artwork) continue;
            try {
                const image = await loadImage(artwork.image);
                if (token !== renderToken) return;
                const rect = layerCanvasRect(layer, area, view, size.width, size.height);
                ctx.save();
                ctx.translate(rect.cx, rect.cy);
                ctx.rotate(layer.rotation * Math.PI / 180);
                ctx.globalAlpha = .98;
                ctx.drawImage(image, -rect.width / 2, -rect.height / 2, rect.width, rect.height);
                if (layer.id === selectedLayerId) {
                    ctx.strokeStyle = "#171614";
                    ctx.lineWidth = 2;
                    ctx.setLineDash([5, 4]);
                    ctx.strokeRect(-rect.width / 2, -rect.height / 2, rect.width, rect.height);
                    ctx.fillStyle = "#171614";
                    ctx.beginPath();
                    ctx.arc(rect.width / 2, rect.height / 2, 5, 0, Math.PI * 2);
                    ctx.fill();
                }
                ctx.restore();
            } catch { /* ignore broken artwork */ }
        }

        if (view.mask) {
            try {
                const mask = await loadImage(view.mask);
                if (token !== renderToken) return;
                ctx.drawImage(mask, 0, 0, size.width / stageZoom, size.height / stageZoom);
            } catch { /* optional */ }
        }
    }

    function renderAll() {
        renderViews();
        renderAreas();
        renderArtworks();
        renderSelection();
        renderPrices();
        zoomLabel.textContent = `${Math.round(stageZoom * 100)}%`;
        if (!has3DStudio) renderCanvas();
    }

    function addLayer(artworkId) {
        const view = activeView(), area = areaById(activeAreaId, view) || view?.areas?.[0], artwork = artworkById(artworkId);
        if (!area || !artwork) return;
        loadImage(artwork.image).then((image) => {
            const bounds = areaBounds(area), aspect = image.naturalWidth / Math.max(1, image.naturalHeight);
            const width = .45;
            const height = clamp((width * bounds.width) / (Math.max(.1, aspect) * bounds.height), .05, .7);
            const candidate = { id: nextLayerId++, artwork_id: artwork.id, area_id: area.id, x: .5, y: .5, width, height, rotation: 0 };
            let found = false;
            for (let i = 0; i < 25; i += 1) {
                candidate.x = .30 + (i % 5) * .10;
                candidate.y = .30 + Math.floor(i / 5) * .10;
                if (isLayerValid(candidate)) { found = true; break; }
            }
            if (!found) {
                saveStatus.textContent = "فضای خالی کافی برای این لیبل در این ناحیه وجود ندارد.";
                return;
            }
            layers.push(candidate);
            selectedLayerId = candidate.id;
            activeAreaId = area.id;
            saveStatus.textContent = "";
            renderAll();
        }).catch(() => { saveStatus.textContent = "تصویر لیبل بارگذاری نشد."; });
    }

    function canvasPoint(event) {
        const rect = canvas.getBoundingClientRect(), view = activeView();
        return { x: ((event.clientX - rect.left) / rect.width) * view.width, y: ((event.clientY - rect.top) / rect.height) * view.height };
    }

    function hitTestLayer(point) {
        const view = activeView();
        const visible = layers.filter((layer) => view.areas?.some((area) => Number(area.id) === Number(layer.area_id))).slice().reverse();
        for (const layer of visible) {
            const area = areaById(layer.area_id, view), rect = layerCanvasRect(layer, area, view, view.width, view.height);
            const local = rotatePoint(point, { x: rect.cx, y: rect.cy }, -layer.rotation * Math.PI / 180);
            if (Math.abs(local.x - rect.cx) <= rect.width / 2 && Math.abs(local.y - rect.cy) <= rect.height / 2) return layer;
        }
        return null;
    }

    function updateLayerPosition(layer, point) {
        const area = areaById(layer.area_id, activeView()), bounds = areaBounds(area);
        const candidate = { ...layer, x: (point.x - bounds.x) / bounds.width, y: (point.y - bounds.y) / bounds.height };
        if (!isLayerValid(candidate, layer.id)) return false;
        layer.x = candidate.x;
        layer.y = candidate.y;
        return true;
    }

    function scaleLayer(layer, factor) {
        const candidate = { ...layer, width: clamp(layer.width * factor, .02, 1), height: clamp(layer.height * factor, .02, 1) };
        if (!isLayerValid(candidate, layer.id)) return false;
        layer.width = candidate.width;
        layer.height = candidate.height;
        return true;
    }

    function rotateLayer(layer, degrees) {
        const candidate = { ...layer, rotation: clamp(layer.rotation + degrees, -180, 180) };
        if (!isLayerValid(candidate, layer.id)) return false;
        layer.rotation = candidate.rotation;
        return true;
    }

    canvas.addEventListener("pointerdown", (event) => {
        const layer = hitTestLayer(canvasPoint(event));
        if (!layer) {
            selectedLayerId = null;
            renderSelection();
            renderCanvas();
            return;
        }
        selectedLayerId = layer.id;
        activeAreaId = layer.area_id;
        dragState = { pointerId: event.pointerId, layer };
        canvas.setPointerCapture(event.pointerId);
        canvas.style.cursor = "grabbing";
        renderSelection();
        renderCanvas();
    });

    canvas.addEventListener("pointermove", (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId) return;
        updateLayerPosition(dragState.layer, canvasPoint(event));
        renderCanvas();
    });

    ["pointerup", "pointercancel"].forEach((type) => canvas.addEventListener(type, (event) => {
        if (!dragState || dragState.pointerId !== event.pointerId) return;
        dragState = null;
        canvas.style.cursor = "default";
        renderAll();
    }));

    canvas.addEventListener("wheel", (event) => {
        event.preventDefault();
        stageZoom = clamp(stageZoom + (event.deltaY < 0 ? .08 : -.08), .7, 1.5);
        zoomLabel.textContent = `${Math.round(stageZoom * 100)}%`;
        renderCanvas();
    }, { passive: false });

    if (!has3DStudio) {
        document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
            const action = button.dataset.action, layer = layers.find((item) => item.id === selectedLayerId);
            if (action === "zoom-in") stageZoom = clamp(stageZoom + .1, .7, 1.5);
            if (action === "zoom-out") stageZoom = clamp(stageZoom - .1, .7, 1.5);
            if (layer && action === "scale-up") scaleLayer(layer, 1.06);
            if (layer && action === "scale-down") scaleLayer(layer, .94);
            if (layer && action === "rotate-left") rotateLayer(layer, -5);
            if (layer && action === "rotate-right") rotateLayer(layer, 5);
            if (layer && action === "delete") {
                const index = layers.findIndex((item) => item.id === layer.id);
                if (index >= 0) layers.splice(index, 1);
                selectedLayerId = null;
            }
            renderAll();
        }));
    }

    variantSelect.addEventListener("change", renderPrices);
    vendorListingSelect?.addEventListener("change", renderPrices);

    if (saveButton) saveButton.addEventListener("click", async () => {
        saveButton.disabled = true;
        saveStatus.textContent = "در حال بررسی و ذخیره طراحی…";
        if (vendorListingSelect && !vendorListingSelect.value) {
            saveStatus.textContent = "برای چاپ سفارشی، ابتدا فروشنده را انتخاب کن.";
            saveButton.disabled = false;
            return;
        }
        const payload = {
            variant_id: variantSelect.value || null,
            vendor_listing_id: vendorListingSelect?.value || null,
            version: 1,
            layers: layers.map(({ artwork_id, area_id, x, y, width, height, rotation }) => ({ artwork_id, area_id, x, y, width, height, rotation })),
        };
        try {
            const response = await fetch(root.dataset.saveUrl, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
                credentials: "same-origin",
                body: JSON.stringify(payload),
            });
            const result = await response.json();
            if (!response.ok || !result.ok) throw new Error(result.error || "ذخیره طراحی انجام نشد.");
            saveStatus.textContent = `طراحی ذخیره شد · کد ${result.draft_id.slice(0, 8)}`;
        } catch (error) {
            saveStatus.textContent = error.message || "ذخیره طراحی انجام نشد.";
        } finally {
            saveButton.disabled = false;
        }
    });

    const sleep = (ms) => new Promise(resolve => window.setTimeout(resolve, ms));

    async function waitForArtwork(statusUrl) {
        for (;;) {
            const response = await fetch(statusUrl, {
                credentials: "same-origin",
                headers: { "Accept": "application/json" },
                cache: "no-store",
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "وضعیت پردازش تصویر دریافت نشد.");
            }
            if (result.status === "ready" && result.artwork) {
                return result.artwork;
            }
            if (result.status === "failed") {
                throw new Error(result.error || "پردازش تصویر ناموفق بود؛ لطفاً دوباره تلاش کنید.");
            }
            uploadStatus.textContent = "در حال حذف هوشمند پس‌زمینه تصویر…";
            await sleep(2500);
        }
    }

    document.getElementById("open-upload")?.addEventListener("click", () => uploadInput.click());
    uploadInput.addEventListener("change", async () => {
        const file = uploadInput.files?.[0];
        if (!file) return;
        const removeBackground = Boolean(removeBackgroundInput?.checked);
        uploadStatus.textContent = removeBackground
            ? "تصویر دریافت شد؛ پردازش در پس‌زمینه انجام می‌شود…"
            : "در حال آپلود تصویر…";
        setProcessingState(removeBackground);
        const form = new FormData();
        form.append("image", file);
        form.append("remove_background", removeBackground ? "1" : "0");
        try {
            const response = await fetch(root.dataset.uploadUrl, {
                method: "POST",
                headers: { "X-CSRFToken": getCookie("csrftoken") },
                credentials: "same-origin",
                body: form,
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "آپلود انجام نشد.");
            }

            const artwork = result.artwork || (
                result.status === "processing"
                    ? await waitForArtwork(result.status_url)
                    : null
            );
            if (!artwork) {
                throw new Error("نتیجه پردازش تصویر نامعتبر است.");
            }

            artwork.is_uploaded = true;
            artworks.push(artwork);
            renderArtworks();

            // Uploading only adds the artwork to the user's library.
            // It must NOT be placed on the garment automatically.
            document.dispatchEvent(new CustomEvent("babaei:artwork-uploaded", {
                detail: { artwork },
            }));
            uploadStatus.textContent = artwork.background_removed
                ? "تصویر آماده شد و به لیبل‌های من اضافه شد."
                : "تصویر آپلود شد و به لیبل‌های من اضافه شد.";
            uploadInput.value = "";
        } catch (error) {
            uploadStatus.textContent = error.message || "آپلود انجام نشد.";
        } finally {
            setProcessingState(false);
        }
    });

    if (!has3DStudio) window.addEventListener("resize", () => renderCanvas());

    renderArtworks();
    renderVariants();

    const labelLibraryTrigger = document.getElementById("label-library-trigger");
    const labelLibraryPanel = document.getElementById("label-library-panel");
    const labelLibraryClose = document.getElementById("label-library-close");

    const setLabelLibraryOpen = (open) => {
        if (!labelLibraryTrigger || !labelLibraryPanel) return;
        labelLibraryPanel.hidden = !open;
        labelLibraryTrigger.setAttribute("aria-expanded", String(open));
        document.body.classList.toggle("label-library-open", open);
    };

    labelLibraryTrigger?.addEventListener("click", () => {
        setLabelLibraryOpen(labelLibraryPanel?.hidden !== false);
    });
    labelLibraryClose?.addEventListener("click", () => setLabelLibraryOpen(false));
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setLabelLibraryOpen(false);
    });

    activeAreaId = views[0]?.areas?.[0]?.id || null;
    renderAll();
})();
