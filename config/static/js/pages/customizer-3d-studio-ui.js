(() => {
    "use strict";
    const root = document.getElementById("customizer");
    if (!root) return;
    let data = {};
    try { data = JSON.parse(document.getElementById("designer-data")?.textContent || "{}"); } catch { return; }

    const variants = data.variants || [];
    const views = data.views || [];
    const select = document.getElementById("variant-select");
    const rotation = document.getElementById("designer-3d-rotation");
    const colorHosts = [document.getElementById("variant-color-list"), document.getElementById("variant-color-list-right")].filter(Boolean);
    const sizeHost = document.getElementById("premium-size-list");
    const viewHost = document.getElementById("view-switcher-mobile");
    const esc = value => String(value ?? "").replace(/[&<>\"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

    function chooseVariant(variant) {
        if (!variant) return;
        if (select) {
            select.value = String(variant.id);
            select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        colorHosts.forEach(host => host.querySelectorAll("button").forEach(button => {
            button.classList.toggle("is-active", button.dataset.color === variant.color);
        }));
        if (sizeHost) sizeHost.querySelectorAll("button").forEach(button => {
            button.classList.toggle("is-active", button.dataset.size === variant.size);
        });
    }

    function renderColors() {
        const seen = new Set();
        const colors = variants.filter(item => {
            if (seen.has(item.color)) return false;
            seen.add(item.color);
            return true;
        });

        colorHosts.forEach(host => {
            host.innerHTML = colors.map(item => `<button type="button" class="premium-color-button" style="--swatch:${item.hex || "#fff"}" data-color="${esc(item.color)}" title="${esc(item.color)}" aria-label="${esc(item.color)}"></button>`).join("");

            host.querySelectorAll("button").forEach(button => button.addEventListener("click", () => {
                const selected = select
                    ? variants.find(item => String(item.id) === String(select.value))
                    : null;

                // Keep the currently selected size when changing color whenever
                // that exact color/size combination is available in stock.
                // Otherwise fall back to the first in-stock size of the new color.
                // Never carry the old color into a size selection implicitly.
                const sameSize = variants.find(item =>
                    item.color === button.dataset.color &&
                    item.size === selected?.size &&
                    Number(item.stock) > 0
                );
                const firstInStock = variants.find(item =>
                    item.color === button.dataset.color &&
                    Number(item.stock) > 0
                );

                chooseVariant(sameSize || firstInStock || null);
            }));
        });
    }

    function renderSizes() {
        if (!sizeHost) return;

        const seen = new Set();
        const sizes = variants.filter(item => {
            if (!item.size || seen.has(item.size)) return false;
            seen.add(item.size);
            return true;
        });

        // A size must stay selectable as long as the product has an active
        // variant for it. Stock is checked when the design is actually added
        // to the cart; disabling the UI here made valid sizes impossible to
        // choose when stock data was zero/stale.
        sizeHost.innerHTML = sizes.map(item => {
            const sizeVariants = variants.filter(
                variant => variant.size === item.size
            );
            const hasStock = sizeVariants.some(
                variant => Number(variant.stock) > 0
            );
            return `<button type="button"
                class="premium-size-button${hasStock ? "" : " is-out-of-stock"}"
                data-size="${esc(item.size)}"
                title="${hasStock ? esc(item.size) : esc(item.size + " — ناموجود")}"
                aria-label="${hasStock ? esc(item.size) : esc(item.size + " — ناموجود")}">
                ${esc(item.size)}
            </button>`;
        }).join("");

        sizeHost.querySelectorAll("button").forEach(button => {
            button.addEventListener("click", () => {
                const selected = select
                    ? variants.find(item => String(item.id) === String(select.value))
                    : null;

                // Only select a real in-stock variant. Otherwise the UI can
                // show a size as selected while the cart API correctly rejects
                // the out-of-stock variant.
                // A size change must NEVER change the selected color.
                // If this color/size combination is unavailable, leave the
                // current variant untouched and tell the user why.
                const sameColor = variants.find(item =>
                    item.size === button.dataset.size &&
                    item.color === selected?.color &&
                    Number(item.stock) > 0
                );

                if (!sameColor) {
                    const message = document.getElementById("save-status");
                    if (message) {
                        message.textContent = `سایز ${button.dataset.size} برای رنگ ${selected?.color || "انتخاب‌شده"} موجود نیست.`;
                    }
                    return;
                }

                chooseVariant(sameColor);
            });
        });;
    }

    function renderViews() {
        if (!viewHost) return;
        const fallback = [
            { name: "جلو", angle: 0 }, { name: "پشت", angle: 180 }, { name: "چپ", angle: -90 }, { name: "راست", angle: 90 },
        ];
        const source = views.length ? views.slice(0, 5) : fallback;
        viewHost.innerHTML = source.map((view, index) => {
            const angle = view.angle != null ? Number(view.angle) : fallback[index]?.angle || 0;
            const image = view.background ? `<img src="${esc(view.background)}" alt="">` : `<span>${esc(view.name || fallback[index]?.name || "نما")}</span>`;
            return `<button type="button" class="studio-view-card ${index === 0 ? "is-active" : ""}" data-angle="${angle}">${image}<b>${esc(view.name || fallback[index]?.name || "نما")}</b></button>`;
        }).join("");
        viewHost.querySelectorAll(".studio-view-card").forEach(button => button.addEventListener("click", () => {
            viewHost.querySelectorAll(".studio-view-card").forEach(item => item.classList.toggle("is-active", item === button));
            if (rotation) {
                const angle = Number(button.dataset.angle || 0);
                rotation.value = String(Math.max(-180, Math.min(180, angle)));
                rotation.dispatchEvent(new Event("input", { bubbles: true }));
            }
        }));
    }

    renderColors();
    renderSizes();
    renderViews();

    /* Fullscreen studio drawers: the 3D garment always stays underneath. */
    const workspace = document.querySelector(".customizer-workspace--premium");
    const leftDrawer = document.querySelector(".customizer-panel--premium-left");
    const rightDrawer = document.querySelector(".customizer-panel--premium-right");
    const leftToggle = document.getElementById("studio-drawer-left-toggle");
    const rightToggle = document.getElementById("studio-drawer-right-toggle");
    const compactMedia = window.matchMedia("(max-width: 1023px)");
    const mobileMedia = window.matchMedia("(max-width: 600px)");

    function setDrawer(side, open) {
        const drawer = side === "left" ? leftDrawer : rightDrawer;
        const toggle = side === "left" ? leftToggle : rightToggle;
        if (!workspace || !drawer || !toggle) return;

        // On phones the controls behave like bottom sheets: only one sheet is
        // allowed to occupy the lower part of the viewport at a time.
        if (open && compactMedia.matches) {
            const other = side === "left" ? "right" : "left";
            const otherDrawer = other === "left" ? leftDrawer : rightDrawer;
            const otherToggle = other === "left" ? leftToggle : rightToggle;
            otherDrawer?.classList.add("is-drawer-closed");
            workspace.classList.add(other === "left" ? "left-drawer-closed" : "right-drawer-closed");
            otherToggle?.setAttribute("aria-expanded", "false");
        }

        drawer.classList.toggle("is-drawer-closed", !open);
        workspace.classList.toggle(side === "left" ? "left-drawer-closed" : "right-drawer-closed", !open);
        toggle.setAttribute("aria-expanded", String(open));
        const anyOpen = !leftDrawer?.classList.contains("is-drawer-closed") || !rightDrawer?.classList.contains("is-drawer-closed");
        const mobileOpen = anyOpen && compactMedia.matches;
        workspace.classList.toggle("mobile-drawer-open", mobileOpen);
        document.dispatchEvent(new CustomEvent("babaei:drawer-state", { detail: { open: mobileOpen, side, drawerOpen: open } }));
        toggle.setAttribute("aria-label", open
            ? (side === "left" ? "بستن ابزار طراحی" : "بستن تنظیمات محصول")
            : (side === "left" ? "باز کردن ابزار طراحی" : "باز کردن تنظیمات محصول"));
    }

    let selectedMobile = false;
    let editingMobile = false;

    // Start with the model unobstructed. The template also carries the closed
    // classes so there is never a flash of two full panels over the 3D model.
    setDrawer("left", false);
    setDrawer("right", false);

    leftToggle?.addEventListener("click", () => {
        const open = leftDrawer?.classList.contains("is-drawer-closed");
        setDrawer("left", open);
    });
    rightToggle?.addEventListener("click", () => {
        const open = rightDrawer?.classList.contains("is-drawer-closed");
        setDrawer("right", open);
    });

    document.querySelectorAll("[data-drawer-close]").forEach(button => {
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();
            setDrawer(button.dataset.drawerClose, false);
        });
    });

    document.getElementById("studio-drawer-backdrop")?.addEventListener("click", () => {
        setDrawer("left", false);
        setDrawer("right", false);
    });

    document.getElementById("label-library-trigger")?.addEventListener("click", () => {
        setDrawer("right", true);
    });

    // After choosing a label, close both sheets and keep the contextual
    // controls in the bottom action area. The 3D model remains unobstructed.
    document.addEventListener("babaei:label-added", () => {
        setDrawer("right", false);
        setDrawer("left", false);

        // A newly added label is immediately the active layer. On mobile,
        // open its edit controls automatically so scale/rotate/move/delete
        // are available without reopening another panel.
        if (mobileMedia.matches) {
            editingMobile = true;
            window.requestAnimationFrame(() => {
                setMobileEditorUi({ selected: true, drawerOpen: false });
            });
        }
    });

    const mobileToolbar = document.getElementById("mobile-customizer-toolbar");
    const mobileSelectionToolbar = document.getElementById("mobile-selection-toolbar");
    const mobileContextToolbar = document.getElementById("mobile-context-toolbar");
    const mobileTextSheet = document.getElementById("mobile-text-sheet");
    const mobileTextInput = document.getElementById("mobile-text-input");
    const mobileColorSheet = document.getElementById("mobile-color-sheet");
    const mobileColorSheetMode = document.getElementById("mobile-color-sheet-mode");
    const mobileColorSheetTitle = document.getElementById("mobile-color-sheet-title");
    const mobileLayerOpacity = document.getElementById("mobile-layer-opacity");
    const mobileLayerOpacityValue = document.getElementById("mobile-layer-opacity-value");
    const mobileLayerColorCustom = document.getElementById("mobile-layer-color-custom");
    const mobileTextSheetMode = document.getElementById("mobile-text-sheet-mode");
    const mobileTextSheetTitle = document.getElementById("mobile-text-sheet-title");
    // Keep mobile sheets outside the workspace stacking/overflow contexts.
    // This guarantees the text action button can never be clipped behind the
    // bottom toolbars on narrow screens.
    [mobileTextSheet, mobileColorSheet, mobileSelectionToolbar]
        .filter(Boolean)
        .forEach(node => {
            if (node.parentElement !== document.body) {
                document.body.appendChild(node);
            }
        });

    const mobileTextAdd = document.getElementById("mobile-text-add");
    const mobileTextCurve = document.getElementById("mobile-text-curve");
    const mobileTextCurveValue = document.getElementById("mobile-text-curve-value");
    const mobileTextSpacing = document.getElementById("mobile-text-spacing");
    const mobileTextSpacingValue = document.getElementById("mobile-text-spacing-value");
    const desktopTextEditor = document.getElementById("desktop-text-editor");
    const desktopTextEditInput = document.getElementById("desktop-text-edit-input");
    const desktopTextSize = document.getElementById("desktop-text-size");
    const desktopTextSizeValue = document.getElementById("desktop-text-size-value");
    const desktopTextCurve = document.getElementById("desktop-text-curve");
    const desktopTextCurveValue = document.getElementById("desktop-text-curve-value");
    const desktopTextSpacing = document.getElementById("desktop-text-spacing");
    const desktopTextSpacingValue = document.getElementById("desktop-text-spacing-value");
    const desktopTextApply = document.getElementById("desktop-text-apply");
    let selectedTextState = null;
    let mobileTextMode = "add";
    let draftTextColor = "#ffffff";
    let draftTextStyle = {
        preset: "modern",
        fontFamily: "Arial, Tahoma, sans-serif",
        fontWeight: 700,
        fontStyle: "normal",
        fontSize: 100,
        curve: 0,
        letterSpacing: 0,
    };

    const TEXT_PRESETS = {
        modern: { fontFamily: "Arial, Tahoma, sans-serif", fontWeight: 700, fontStyle: "normal" },
        classic: { fontFamily: "Georgia, 'Times New Roman', serif", fontWeight: 700, fontStyle: "normal" },
        impact: { fontFamily: "Impact, Haettenschweiler, sans-serif", fontWeight: 900, fontStyle: "normal" },
        mono: { fontFamily: "'Courier New', monospace", fontWeight: 700, fontStyle: "normal" },
        elegant: { fontFamily: "Georgia, 'Times New Roman', serif", fontWeight: 400, fontStyle: "italic" },
    };

    function normalizedTextStyle(style = {}) {
        return {
            ...(draftTextStyle || {}),
            ...style,
            fontSize: Math.max(60, Math.min(160, Number(style.fontSize ?? draftTextStyle.fontSize ?? 100))),
            curve: Math.max(-80, Math.min(80, Number(style.curve ?? draftTextStyle.curve ?? 0))),
            letterSpacing: Math.max(-2, Math.min(12, Number(style.letterSpacing ?? draftTextStyle.letterSpacing ?? 0))),
        };
    }

    function paintTextControls(style = {}, color = "#ffffff") {
        const next = normalizedTextStyle(style);
        draftTextStyle = next;
        draftTextColor = color || draftTextColor;
        if (mobileTextCurve) mobileTextCurve.value = String(next.curve);
        if (mobileTextCurveValue) mobileTextCurveValue.textContent = String(next.curve);
        if (mobileTextSpacing) mobileTextSpacing.value = String(next.letterSpacing);
        if (mobileTextSpacingValue) mobileTextSpacingValue.textContent = String(next.letterSpacing);
        if (desktopTextSize) desktopTextSize.value = String(next.fontSize);
        if (desktopTextSizeValue) desktopTextSizeValue.textContent = String(next.fontSize);
        if (desktopTextCurve) desktopTextCurve.value = String(next.curve);
        if (desktopTextCurveValue) desktopTextCurveValue.textContent = String(next.curve);
        if (desktopTextSpacing) desktopTextSpacing.value = String(next.letterSpacing);
        if (desktopTextSpacingValue) desktopTextSpacingValue.textContent = String(next.letterSpacing);
        document.querySelectorAll("[data-text-style]").forEach(button => {
            button.classList.toggle("is-active", button.dataset.textStyle === next.preset);
        });
        document.querySelectorAll("[data-text-color]").forEach(button => {
            button.classList.toggle("is-active", button.dataset.textColor === draftTextColor);
        });
    }

    function closeMobileText() {
        if (mobileTextSheet) mobileTextSheet.hidden = true;
        const drawerOpen = !leftDrawer?.classList.contains("is-drawer-closed") ||
            !rightDrawer?.classList.contains("is-drawer-closed");
        if (!drawerOpen) document.body.classList.remove("customizer-mobile-sheet-open");
        setMobileEditorUi({ selected: selectedMobile, drawerOpen });
    }

    function openMobileText() {
        if (!mobileTextSheet) return;

        mobileTextMode = selectedTextState ? "edit" : "add";
        if (mobileTextMode === "edit") {
            if (mobileTextInput) mobileTextInput.value = selectedTextState.text || "";
            if (mobileTextSheetMode) mobileTextSheetMode.textContent = "ویرایش متن";
            if (mobileTextSheetTitle) mobileTextSheetTitle.textContent = "طراحی متن انتخاب‌شده";
            if (mobileTextAdd) mobileTextAdd.textContent = "اعمال تغییرات متن";
            paintTextControls(selectedTextState.textStyle || {}, selectedTextState.color || "#ffffff");
        } else {
            if (mobileTextInput) mobileTextInput.value = "";
            if (mobileTextSheetMode) mobileTextSheetMode.textContent = "افزودن به لباس";
            if (mobileTextSheetTitle) mobileTextSheetTitle.textContent = "متن خودت را بنویس";
            if (mobileTextAdd) mobileTextAdd.textContent = "افزودن متن به تیشرت";
            paintTextControls({}, draftTextColor);
        }

        mobileTextSheet.hidden = false;
        document.body.classList.add("customizer-mobile-sheet-open");
        mobileTextInput?.focus();
    }

    function setMobileEditorUi({ selected = selectedMobile, drawerOpen = false } = {}) {
        if (drawerOpen || !mobileMedia.matches) {
            mobileToolbar?.classList.toggle("is-hidden", drawerOpen);
            mobileSelectionToolbar?.setAttribute("hidden", "");
            mobileContextToolbar?.setAttribute("hidden", "");
            return;
        }

        // The three size/delete controls are a permanent mobile side menu.
        // They must not replace the main toolbar and must stay visible even when
        // the current label is deleted; without a selection their actions simply
        // have nothing to modify.
        mobileToolbar?.classList.remove("is-hidden");
        mobileContextToolbar?.setAttribute("hidden", "");
        mobileSelectionToolbar?.removeAttribute("hidden");
        editingMobile = Boolean(selected) || editingMobile;
    }

    function openMobileEdit() {
        editingMobile = true;
        mobileToolbar?.classList.remove("is-hidden");
        mobileContextToolbar?.setAttribute("hidden", "");
        mobileSelectionToolbar?.removeAttribute("hidden");
    }

    function closeMobileEdit() {
        editingMobile = false;
        setMobileEditorUi({ selected: selectedMobile, drawerOpen: false });
    }

    function openMobileColorSheet(mode = "color") {
        if (!mobileColorSheet) return;
        if (mobileColorSheetMode) mobileColorSheetMode.textContent = mode === "paint" ? "ویرایش رنگ طرح" : "ویرایش طرح";
        if (mobileColorSheetTitle) mobileColorSheetTitle.textContent = mode === "paint" ? "رنگ‌آمیزی طرح" : "رنگ طرح";
        mobileColorSheet.hidden = false;
        document.body.classList.add("customizer-mobile-sheet-open");
        document.dispatchEvent(new CustomEvent("babaei:mobile-color-sheet", { detail: { open: true, mode } }));
    }

    function closeMobileColorSheet() {
        if (mobileColorSheet) mobileColorSheet.hidden = true;
        const drawerOpen = !leftDrawer?.classList.contains("is-drawer-closed") ||
            !rightDrawer?.classList.contains("is-drawer-closed");
        if (!drawerOpen && mobileTextSheet?.hidden !== false) document.body.classList.remove("customizer-mobile-sheet-open");
        setMobileEditorUi({ selected: selectedMobile, drawerOpen });
        document.dispatchEvent(new CustomEvent("babaei:mobile-color-sheet", { detail: { open: false } }));
    }

    // Mobile tool sheets intentionally mirror the desktop tools one-by-one.
    // They use the same source controls, but never open the desktop dock or the
    // full product drawers. This keeps every action independent and touch-safe.
    const mobileToolSheet = document.getElementById("mobile-tool-sheet");
    const mobileToolSheetBody = document.getElementById("mobile-tool-sheet-body");
    const mobileToolSheetTitle = document.getElementById("mobile-tool-sheet-title");
    // Move the tool sheet only after its DOM reference has been initialized.
    // Keeping this below the const declarations avoids a TDZ error that would
    // stop the entire mobile UI script from binding its click handlers.
    if (mobileToolSheet && mobileToolSheet.parentElement !== document.body) {
        document.body.appendChild(mobileToolSheet);
    }

    function closeMobileToolSheet() {
        if (!mobileToolSheet) return;
        mobileToolSheet.hidden = true;
        mobileToolSheetBody && (mobileToolSheetBody.innerHTML = "");
        if (!mobileTextSheet?.hidden) return;
        if (!mobileColorSheet?.hidden) return;
        document.body.classList.remove("customizer-mobile-sheet-open");
    }

    function openMobileToolSheet(title, node) {
        if (!mobileToolSheet || !mobileToolSheetBody) return;

        // Only one mobile sheet may own the lock at a time.
        mobileTextSheet && (mobileTextSheet.hidden = true);
        mobileColorSheet && (mobileColorSheet.hidden = true);

        mobileToolSheetTitle && (mobileToolSheetTitle.textContent = title);
        mobileToolSheetBody.innerHTML = "";
        mobileToolSheetBody.appendChild(node);
        mobileToolSheet.hidden = false;
        document.body.classList.add("customizer-mobile-sheet-open");
    }

    // Every mobile sheet has its own close path. Never leave the body locked
    // when the user closes a sheet with X or by tapping the backdrop.
    mobileToolSheet?.querySelector("#mobile-tool-sheet-close")?.addEventListener("click", closeMobileToolSheet);
    mobileToolSheet?.querySelector("#mobile-tool-sheet-backdrop")?.addEventListener("click", closeMobileToolSheet);

    function cloneMobileSource(selector, { unhide = false } = {}) {
        const source = document.querySelector(selector);
        if (!source) return null;
        const node = source.cloneNode(true);
        node.removeAttribute("id");
        node.querySelectorAll("[id]").forEach(item => item.removeAttribute("id"));
        if (unhide) node.removeAttribute("hidden");
        return { source, node };
    }

    function openMobileLabelTool() {
        const sourcePanel = document.querySelector("#label-library-panel");
        if (!sourcePanel) return;

        // Do NOT clone the desktop panel itself. The desktop drawer carries
        // desktop width/grid rules and was the reason the phone library kept
        // collapsing into a narrow column.
        const wrapper = document.createElement("div");
        wrapper.className = "mobile-label-library";

        const sections = sourcePanel.querySelectorAll(".artwork-library-section");
        sections.forEach(sourceSection => {
            const section = document.createElement("section");
            section.className = "mobile-label-library__section";
            section.dataset.artworkSection =
                sourceSection.dataset.artworkSection || "";

            const sourceToggle = sourceSection.querySelector(
                ".artwork-library-section__toggle"
            );
            const toggle = document.createElement("button");
            toggle.type = "button";
            toggle.className = "mobile-label-library__toggle";
            toggle.innerHTML = sourceToggle?.innerHTML || (
                sourceSection.dataset.artworkSection === "uploaded"
                    ? "<span>لیبل‌های من</span><span>⌄</span>"
                    : "<span>کتابخانه لیبل‌ها</span><span>⌄</span>"
            );
            toggle.setAttribute("aria-controls", "mobile-label-section-" + section.dataset.artworkSection);
            toggle.setAttribute(
                "aria-expanded",
                sourceToggle?.getAttribute("aria-expanded") !== "false"
                    ? "true"
                    : "false"
            );

            const sourceGrid = sourceSection.querySelector(
                ".artwork-library-section__grid, .artwork-grid"
            );
            const grid = document.createElement("div");
            grid.className = "mobile-label-library__grid";
            grid.id = "mobile-label-section-" + section.dataset.artworkSection;
            grid.hidden = toggle.getAttribute("aria-expanded") === "false";

            const sourceButtons = sourceGrid
                ? Array.from(sourceGrid.querySelectorAll("button"))
                : [];

            sourceButtons.forEach(sourceButton => {
                const card = sourceButton.cloneNode(true);
                card.removeAttribute("id");
                card.disabled = sourceButton.disabled;
                card.classList.add("mobile-label-library__card");
                card.style.width = "100%";
                card.style.minWidth = "0";
                card.style.maxWidth = "none";
                card.style.boxSizing = "border-box";

                card.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    sourceButton.click();
                    closeMobileToolSheet();
                });

                grid.appendChild(card);
            });

            toggle.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();

                const willOpen = grid.hidden;
                wrapper.querySelectorAll(".mobile-label-library__grid").forEach(item => {
                    item.hidden = true;
                });
                wrapper.querySelectorAll(".mobile-label-library__toggle").forEach(item => {
                    item.setAttribute("aria-expanded", "false");
                });

                if (willOpen) {
                    grid.hidden = false;
                    toggle.setAttribute("aria-expanded", "true");
                }
            });

            section.append(toggle, grid);
            wrapper.appendChild(section);
        });

        const sourceUpload = sourcePanel.querySelector("#artwork-upload");
        const sourceDropzone = sourcePanel.querySelector(".upload-dropzone");
        if (sourceUpload && sourceDropzone) {
            const upload = sourceDropzone.cloneNode(true);
            upload.removeAttribute("id");
            upload.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                sourceUpload.click();
            });
            wrapper.appendChild(upload);
        }

        openMobileToolSheet("انتخاب لیبل", wrapper);
    }

    function syncMobileClonedButtons(result) {
        const sourceButtons = result.source.querySelectorAll("button");
        const clonedButtons = result.node.querySelectorAll("button");
        clonedButtons.forEach((button, index) => {
            const source = sourceButtons[index];
            if (!source) return;
            button.classList.toggle("is-active", source.classList.contains("is-active"));
            button.classList.toggle("is-out-of-stock", source.classList.contains("is-out-of-stock"));
            button.disabled = source.disabled;
            button.setAttribute("aria-pressed", source.classList.contains("is-active") ? "true" : "false");
        });
    }

    function openMobileChoiceTool(selector, title) {
        const result = cloneMobileSource(selector, { unhide: true });
        if (!result) return;

        const sourceButtons = result.source.querySelectorAll("button");
        result.node.querySelectorAll("button").forEach((button, index) => {
            button.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                sourceButtons[index]?.click();
                requestAnimationFrame(() => syncMobileClonedButtons(result));
            });
        });

        syncMobileClonedButtons(result);
        openMobileToolSheet(title, result.node);
    }


    document.addEventListener("babaei:artwork-uploaded", () => {
        // The desktop library is the source of truth. Rebuild the mobile copy
        // while it is open so "لیبل‌های من" matches the desktop immediately.
        if (
            mobileToolSheet &&
            !mobileToolSheet.hidden &&
            mobileToolSheetBody?.querySelector(".mobile-label-library")
        ) {
            openMobileLabelTool();
        }
    });

    document.querySelectorAll("[data-mobile-action]").forEach(button => {
        button.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            const action = button.dataset.mobileAction;

            if (action === "label") {
                openMobileLabelTool();
                return;
            }
            if (action === "shirt-color") {
                openMobileChoiceTool("#variant-color-list-right", "رنگ تیشرت");
                return;
            }
            if (action === "size") {
                openMobileChoiceTool("#premium-size-list", "انتخاب سایز");
                return;
            }
            if (action === "garment") {
                openMobileGarmentTool();
                return;
            }
            if (action === "save") {
                document.getElementById("add-to-cart-design")?.click();
                return;
            }
            if (action === "text" || action === "text-font") {
                openMobileText();
            }
        });
    });


    document.getElementById("mobile-text-close")?.addEventListener("click", closeMobileText);
    mobileTextAdd?.addEventListener("click", () => {
        const value = mobileTextInput?.value?.trim();
        if (!value) {
            mobileTextInput?.focus();
            return;
        }

        const detail = {
            text: value,
            style: draftTextStyle,
            color: draftTextColor,
        };

        document.dispatchEvent(new CustomEvent(
            mobileTextMode === "edit" ? "babaei:update-text" : "babaei:add-text",
            { detail }
        ));

        if (mobileTextInput) mobileTextInput.value = "";
        closeMobileText();
    });

    const desktopTextInput = document.getElementById("desktop-text-input");
    const desktopTextAdd = document.getElementById("desktop-text-add");

    function addDesktopText() {
        const value = desktopTextInput?.value?.trim();
        if (!value) {
            desktopTextInput?.focus();
            return;
        }
        document.dispatchEvent(new CustomEvent("babaei:add-text", { detail: { text: value } }));
        if (desktopTextInput) {
            desktopTextInput.value = "";
            desktopTextInput.focus();
        }
    }

    desktopTextAdd?.addEventListener("click", addDesktopText);
    desktopTextInput?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            addDesktopText();
        }
    });

    desktopTextApply?.addEventListener("click", () => {
        if (!selectedTextState) return;
        const value = desktopTextEditInput?.value?.trim();
        if (!value) {
            desktopTextEditInput?.focus();
            return;
        }

        document.dispatchEvent(new CustomEvent("babaei:update-text", {
            detail: {
                text: value,
                style: draftTextStyle,
                color: draftTextColor,
            }
        }));
    });

    document.querySelectorAll("[data-text-style]").forEach(button => {
        button.addEventListener("click", () => {
            const preset = TEXT_PRESETS[button.dataset.textStyle];
            if (!preset) return;

            draftTextStyle = {
                ...draftTextStyle,
                ...preset,
                preset: button.dataset.textStyle,
            };

            paintTextControls(draftTextStyle, draftTextColor);

            if (selectedTextState) {
                document.dispatchEvent(new CustomEvent("babaei:update-text-style", {
                    detail: { style: draftTextStyle }
                }));
            }
        });
    });

    function wireTextRange(input, output, key) {
        input?.addEventListener("input", () => {
            const value = Number(input.value);
            draftTextStyle = {
                ...draftTextStyle,
                [key]: value,
            };
            if (output) output.textContent = String(value);

            if (selectedTextState) {
                document.dispatchEvent(new CustomEvent("babaei:update-text-style", {
                    detail: { style: draftTextStyle }
                }));
            }
        });
    }

    wireTextRange(mobileTextCurve, mobileTextCurveValue, "curve");
    wireTextRange(mobileTextSpacing, mobileTextSpacingValue, "letterSpacing");
    wireTextRange(desktopTextSize, desktopTextSizeValue, "fontSize");
    wireTextRange(desktopTextCurve, desktopTextCurveValue, "curve");
    wireTextRange(desktopTextSpacing, desktopTextSpacingValue, "letterSpacing");

    document.querySelectorAll("[data-text-color]").forEach(button => {
        button.addEventListener("click", () => {
            const color = button.dataset.textColor;
            if (!color) return;
            draftTextColor = color;
            document.querySelectorAll("[data-text-color]").forEach(item => {
                item.classList.toggle("is-active", item === button);
            });

            if (selectedTextState) {
                document.dispatchEvent(new CustomEvent("babaei:set-layer-color", {
                    detail: { color }
                }));
            }
        });
    });

    document.addEventListener("babaei:drawer-state", event => {
        const open = Boolean(event.detail?.open);
        document.body.classList.toggle("customizer-mobile-sheet-open", open);
        setMobileEditorUi({ selected: Boolean(selectedMobile), drawerOpen: open });
    });

    document.addEventListener("babaei:selection-changed", event => {
        selectedMobile = Boolean(event.detail?.selected);
        selectedTextState = event.detail?.isText
            ? {
                id: event.detail.id,
                text: String(event.detail.text || ""),
                textStyle: event.detail.textStyle || {},
                color: event.detail.color || "#ffffff",
            }
            : null;
        if (!selectedMobile) editingMobile = false;

        if (desktopTextEditor) {
            desktopTextEditor.hidden = !selectedTextState;
            if (selectedTextState) {
                if (desktopTextEditInput) desktopTextEditInput.value = selectedTextState.text;
                paintTextControls(selectedTextState.textStyle, selectedTextState.color);
            }
        }

        const drawerOpen = Boolean(
            !leftDrawer?.classList.contains("is-drawer-closed") ||
            !rightDrawer?.classList.contains("is-drawer-closed")
        );
        setMobileEditorUi({ selected: selectedMobile, drawerOpen });
    });

    document.querySelectorAll("[data-mobile-selection]").forEach(button => {
        button.addEventListener("click", () => {
            const action = button.dataset.mobileSelection;
            if (action === "layout") setDrawer("left", true);
            if (action === "done") closeMobileEdit();
        });
    });


    document.querySelectorAll("[data-mobile-context]").forEach(button => {
        button.addEventListener("click", () => {
            const action = button.dataset.mobileContext;
            if (action === "color") openMobileColorSheet("color");
            if (action === "text") openMobileText();
            if (action === "background") setDrawer("right", true);
            if (action === "edit") openMobileEdit();
        });
    });

    document.getElementById("mobile-color-sheet-close")?.addEventListener("click", closeMobileColorSheet);
    document.getElementById("mobile-color-sheet-done")?.addEventListener("click", closeMobileColorSheet);

    document.querySelectorAll("[data-layer-color]").forEach(button => {
        button.addEventListener("click", () => {
            document.dispatchEvent(new CustomEvent("babaei:set-layer-color", {
                detail: { color: button.dataset.layerColor }
            }));
            document.querySelectorAll("[data-layer-color]").forEach(item => item.classList.toggle("is-active", item === button));
            if (mobileLayerColorCustom) mobileLayerColorCustom.value = button.dataset.layerColor;
        });
    });

    mobileLayerColorCustom?.addEventListener("input", () => {
        const color = mobileLayerColorCustom.value;
        document.dispatchEvent(new CustomEvent("babaei:set-layer-color", { detail: { color } }));
    });

    mobileLayerOpacity?.addEventListener("input", () => {
        const value = Number(mobileLayerOpacity.value || 100);
        if (mobileLayerOpacityValue) mobileLayerOpacityValue.textContent = value + "%";
        document.dispatchEvent(new CustomEvent("babaei:set-layer-opacity", {
            detail: { opacity: value / 100 }
        }));
    });

    document.addEventListener("babaei:mobile-color-sheet", event => {
        const open = Boolean(event.detail?.open);
        if (open) {
            editingMobile = false;
            mobileToolbar?.classList.add("is-hidden");
            mobileSelectionToolbar?.setAttribute("hidden", "");
            mobileContextToolbar?.setAttribute("hidden", "");
        } else {
            setMobileEditorUi({ selected: selectedMobile, drawerOpen: false });
        }
    });

    document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        if (mobileColorSheet && !mobileColorSheet.hidden) {
            closeMobileColorSheet();
            return;
        }
        if (mobileTextSheet && !mobileTextSheet.hidden) {
            closeMobileText();
            return;
        }
        if (editingMobile) {
            closeMobileEdit();
            return;
        }
        const drawerOpen = !leftDrawer?.classList.contains("is-drawer-closed") ||
            !rightDrawer?.classList.contains("is-drawer-closed");
        if (drawerOpen) {
            setDrawer("left", false);
            setDrawer("right", false);
        }
    });

    window.BabaeiStudioDrawers = {
        open: side => setDrawer(side, true),
        close: side => setDrawer(side, false),
        toggle: side => {
            const drawer = side === "left" ? leftDrawer : rightDrawer;
            setDrawer(side, drawer?.classList.contains("is-drawer-closed"));
        },
    };



    const current = variants.find(item => String(item.id) === String(select?.value)) || variants.find(item => Number(item.stock) > 0) || variants[0];
    if (current) chooseVariant(current);
})();
