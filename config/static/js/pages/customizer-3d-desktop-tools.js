(() => {
    "use strict";

    function initDesktopToolDock() {
        const LOG = "[BABAEI][DESKTOP-TOOLS]";
        const log = (...args) => console.log(LOG, ...args);
        const warn = (...args) => console.warn(LOG, ...args);
        const error = (...args) => console.error(LOG, ...args);

        log("INIT: desktop tools script started", {
            readyState: document.readyState,
            width: window.innerWidth,
            height: window.innerHeight,
        });

        const dock = document.getElementById("desktop-tool-dock");
        const popover = document.getElementById("desktop-tool-popover");
        const selectedToolsButton = document.getElementById("desktop-selected-tools-button");


        log("DOM CHECK", {
            dock: !!dock,
            popover: !!popover,
            dockButtons: dock?.querySelectorAll("[data-desktop-tool]").length ?? 0,
        });

        if (!dock || !popover) {
            error("INIT FAILED: dock or popover element not found");
            return;
        }

        if (dock.dataset.bound === "1") {
            warn("INIT SKIPPED: dock is already bound");
            return;
        }

        dock.dataset.bound = "1";
        log("INIT OK: event binding begins");

        let currentTool = null;

        let leftPopover = document.getElementById("desktop-label-tools-popover");
        if (!leftPopover) {
            leftPopover = document.createElement("div");
            leftPopover.id = "desktop-label-tools-popover";
            leftPopover.className = "desktop-tool-popover desktop-tool-popover--left";
            leftPopover.hidden = true;
            (dock.closest(".customizer-workspace--premium") || document.body).appendChild(leftPopover);
        }

        const closeLeftPopover = () => {
            leftPopover.hidden = true;
            leftPopover.innerHTML = "";
        };

        const close = () => {
            log("POPOVER CLOSE");
            popover.hidden = true;
            popover.classList.remove("desktop-tool-popover--left");
            popover.innerHTML = "";
            // The selected-label tools panel is independent and stays visible
            // while regular right-side tools are being used.
            if (currentTool === "label-tools") {
                closeLeftPopover();
            }
        };

        const open = (title, node, side = "right") => {
            log("POPOVER OPEN", {
                title,
                node: node?.className || node?.tagName || null,
            });

            popover.innerHTML = "";

            // Regular tools always open beside the right-side grid.
            // Only the dedicated selected-label tools panel is allowed on the left.
            popover.classList.remove("desktop-tool-popover--left");
            if (side === "left") {
                popover.classList.add("desktop-tool-popover--left");
            }

            const header = document.createElement("div");
            header.className = "desktop-tool-popover__title";

            const label = document.createElement("span");
            label.textContent = title;

            const closeButton = document.createElement("button");
            closeButton.type = "button";
            closeButton.className = "desktop-tool-popover__close";
            closeButton.setAttribute("aria-label", "بستن");
            closeButton.textContent = "×";
            closeButton.addEventListener("click", close);

            header.append(label, closeButton);
            popover.append(header, node);
            popover.hidden = false;

            log("POPOVER STATE", {
                hidden: popover.hidden,
                display: getComputedStyle(popover).display,
                visibility: getComputedStyle(popover).visibility,
                opacity: getComputedStyle(popover).opacity,
                rect: popover.getBoundingClientRect().toJSON(),
            });
        };

        const clone = (selector, options = {}) => {
            const source = document.querySelector(selector);

            log("CLONE REQUEST", {
                selector,
                found: !!source,
                hidden: source?.hidden,
                display: source ? getComputedStyle(source).display : null,
            });

            if (!source) {
                warn("CLONE FAILED: source not found", selector);
                return null;
            }

            const node = source.cloneNode(true);
            if (options.removeId !== false) {
                node.removeAttribute("id");
                node.querySelectorAll("[id]").forEach(item => item.removeAttribute("id"));
            }
            if (options.unhide) node.removeAttribute("hidden");
            return { source, node };
        };

        const dispatch = (name, detail = {}) => {
            log("DISPATCH", { name, detail });
            document.dispatchEvent(new CustomEvent(name, { detail }));
        };

        const openLabel = (focusUploaded = false) => {
            currentTool = "label";
            log("ACTION: label");
            const result = clone("#label-library-panel", { unhide: true });
            if (!result) return;

            // The desktop popover already has its own single × in the header.
            // Remove the old panel header so there is no second close button.
            result.node.querySelector(".label-library-panel__head")?.remove();

            const librarySection = result.node.querySelector('[data-artwork-section="library"]');
            const libraryToggle = librarySection?.querySelector(".artwork-library-section__toggle");
            if (libraryToggle) {
                const description = document.createElement("small");
                description.className = "artwork-library-section__description";
                description.textContent = "یک لیبل انتخاب کن تا روی لباس قرار بگیرد.";
                libraryToggle.appendChild(description);
            }

            const librarySectionNode = result.node.querySelector('[data-artwork-section="library"]');
            const uploadedSectionNode = result.node.querySelector('[data-artwork-section="uploaded"]');
            const setSectionState = (section, openState) => {
                const toggle = section?.querySelector(".artwork-library-section__toggle");
                const grid = section?.querySelector(".artwork-library-section__grid");
                if (!toggle || !grid) return;
                const body = section.querySelector(".artwork-library-section__body");
                if (body) body.hidden = !openState;
                grid.hidden = !openState;
                toggle.setAttribute("aria-expanded", String(openState));
                section.classList.toggle("is-open", openState);
            };

            // Lead with the personal-label path. The ready-made library is
            // intentionally collapsed so the upload action is visible immediately.
            setSectionState(librarySectionNode, false);
            setSectionState(uploadedSectionNode, true);

            result.node.querySelectorAll("[data-artwork-section] .artwork-library-section__toggle").forEach(toggle => {
                toggle.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    const section = toggle.closest("[data-artwork-section]");
                    const grid = section?.querySelector(".artwork-library-section__grid");
                    if (!grid) return;
                    const isOpen = !grid.hidden;
                    const nextOpen = !isOpen;
                    const sibling = section.parentElement?.querySelector(
                        '[data-artwork-section].is-open'
                    );
                    if (nextOpen && sibling && sibling !== section) {
                        setSectionState(sibling, false);
                    }

                    const body = section.querySelector(".artwork-library-section__body");
                    if (body) {
                        body.hidden = !nextOpen;
                        grid.hidden = !nextOpen;
                    } else {
                        grid.hidden = !nextOpen;
                    }

                    toggle.setAttribute("aria-expanded", String(nextOpen));
                    section.classList.toggle("is-open", nextOpen);
                    log("LABEL SECTION TOGGLE", {
                        section: section.dataset.artworkSection,
                        open: !isOpen,
                    });
                });
            });

            const sourceButtons = result.source.querySelectorAll(".artwork-grid button");
            result.node.querySelectorAll(".artwork-grid button").forEach((button, index) => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    log("LABEL SELECT", { index });
                    sourceButtons[index]?.click();
                    // Keep the library popover open. The user closes it explicitly with ×.
                });
            });

            // Keep the upload controls inside the separate "لیبل‌های من" box.
            const uploadedSection = result.node.querySelector('[data-artwork-section="uploaded"]');
            const uploadDropzone = result.node.querySelector(".upload-dropzone");
            const backgroundOption = result.node.querySelector(".upload-background-option");
            const uploadStatus = result.node.querySelector("#upload-status");
            if (uploadedSection && uploadDropzone) {
                const uploadedGrid = uploadedSection.querySelector(".artwork-library-section__grid");

                // Keep the upload controls inside the "لیبل‌های من" section and
                // hide them together with its label grid when the section closes.
                // When opened, the controls appear first and the user's labels
                // appear immediately underneath them.
                const uploadedBody = document.createElement("div");
                uploadedBody.className = "artwork-library-section__body";

                uploadedBody.appendChild(uploadDropzone);
                if (backgroundOption) {
                    uploadedBody.appendChild(backgroundOption);
                }
                if (uploadStatus) {
                    uploadedBody.appendChild(uploadStatus);
                }
                if (uploadedGrid) {
                    uploadedBody.appendChild(uploadedGrid);
                }

                uploadedSection.appendChild(uploadedBody);
                if (uploadedGrid) {
                    uploadedGrid.hidden = !uploadedSection.classList.contains("is-open");
                }
                uploadedBody.hidden = !uploadedSection.classList.contains("is-open");
            }

            const sourceUpload = result.source.querySelector("#artwork-upload");
            const sourceBackgroundInput = result.source.querySelector("#artwork-remove-background");
            const clonedBackgroundInput = backgroundOption?.querySelector('input[type="checkbox"]');

            // The desktop label picker is a clone of the real upload controls.
            // Keep the cloned checkbox synchronized with the real checkbox so
            // customizer.js sends the correct remove_background value to Django.
            if (sourceBackgroundInput && clonedBackgroundInput) {
                clonedBackgroundInput.checked = sourceBackgroundInput.checked;
                clonedBackgroundInput.addEventListener("change", () => {
                    sourceBackgroundInput.checked = clonedBackgroundInput.checked;
                });
            }

            const uploadButton = result.node.querySelector(".upload-dropzone");
            if (sourceUpload && uploadButton) {
                uploadButton.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    sourceUpload.value = "";
                    sourceUpload.click();
                });
            }
            const panelClose = result.node.querySelector(".label-library-close");
            panelClose?.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                log("LABEL LIBRARY CLOSE");
                close();
            });

            result.node.querySelector('input[type="file"]')?.remove();

            open("انتخاب لیبل", result.node);
        };

        document.addEventListener("babaei:artwork-uploaded", event => {
            log("ARTWORK UPLOADED", { artwork: event.detail?.artwork });

            // Refresh the currently open label picker after an upload. Do not
            // depend on currentTool alone: the upload is launched from a cloned
            // panel, so the tool state can be changed while the native file
            // input is processing the request.
            const labelPickerOpen = !popover.hidden &&
                Boolean(popover.querySelector(".upload-dropzone"));
            if (labelPickerOpen) {
                requestAnimationFrame(() => openLabel(true));
            }
        });

        const openButtons = (selector, title) => {
            currentTool = selector;
            log("ACTION: button group", { selector, title });
            const result = clone(selector);
            if (!result) return;

            const sourceButtons = result.source.querySelectorAll("button");
            result.node.querySelectorAll("button").forEach((button, index) => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();

                    const sourceButton = sourceButtons[index];
                    sourceButton?.click();

                    // The desktop popover is a clone of the real control list.
                    // The source button changes state, but cloneNode does not
                    // receive that DOM update automatically. Mirror the state
                    // immediately so size/color selections are visible without
                    // closing and reopening the popover.
                    requestAnimationFrame(() => {
                        result.node.querySelectorAll("button").forEach((cloneButton, cloneIndex) => {
                            const source = sourceButtons[cloneIndex];
                            if (!source) return;
                            cloneButton.classList.toggle("is-active", source.classList.contains("is-active"));
                            cloneButton.classList.toggle("is-disabled", source.classList.contains("is-disabled"));
                            cloneButton.classList.toggle("is-out-of-stock", source.classList.contains("is-out-of-stock"));
                            cloneButton.disabled = source.disabled;
                            cloneButton.setAttribute("aria-pressed", source.classList.contains("is-active") ? "true" : "false");
                        });
                    });

                    // Keep the tool card open until the explicit × is pressed.
                });
            });

            open(title, result.node);
        };

        const wireTextEditor = (editorResult) => {
            if (!editorResult) return;

            const source = editorResult.source;
            const node = editorResult.node;
            const editInput = node.querySelector('input[type="text"]');
            const sourceEditInput = source.querySelector("#desktop-text-edit-input");
            const apply = node.querySelector(".desktop-text-editor__apply");
            const sourceApply = source.querySelector("#desktop-text-apply");

            if (editInput && sourceEditInput) {
                editInput.value = sourceEditInput.value || "";
            }

            node.querySelectorAll("[data-text-style]").forEach(button => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();

                    const selector = '[data-text-style="' +
                        CSS.escape(button.dataset.textStyle || "") +
                        '"]';
                    const original = Array.from(document.querySelectorAll(selector))
                        .find(item => item !== button);

                    log("TEXT STYLE SELECT", { style: button.dataset.textStyle });
                    original?.click();
                });
            });

            const sourceRanges = source.querySelectorAll('input[type="range"]');
            node.querySelectorAll('input[type="range"]').forEach((range, index) => {
                range.addEventListener("input", () => {
                    const original = sourceRanges[index];
                    if (!original) return;

                    original.value = range.value;
                    original.dispatchEvent(new Event("input", { bubbles: true }));
                });
            });

            node.querySelectorAll("[data-text-color]").forEach(button => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();

                    const color = button.dataset.textColor;
                    const original = Array.from(document.querySelectorAll("[data-text-color]"))
                        .find(item => item !== button && item.dataset.textColor === color);

                    log("TEXT COLOR SELECT", { color });
                    original?.click();
                });
            });

            apply?.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();

                const value = editInput?.value?.trim();
                if (!value) {
                    editInput?.focus();
                    return;
                }

                const sourceColor = Array.from(document.querySelectorAll("[data-text-color].is-active"))
                    .find(item => item.dataset.textColor)?.dataset.textColor || "#ffffff";

                const style = {
                    preset: Array.from(document.querySelectorAll("[data-text-style].is-active"))
                        .find(item => item.dataset.textStyle)?.dataset.textStyle || "modern",
                    curve: Number(source.querySelector("#desktop-text-curve")?.value || 0),
                    letterSpacing: Number(source.querySelector("#desktop-text-spacing")?.value || 0),
                };

                log("TEXT APPLY", { value, style, color: sourceColor });
                dispatch("babaei:update-text", {
                    text: value,
                    style,
                    color: sourceColor,
                });
            });

            editInput?.addEventListener("keydown", event => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                apply?.click();
            });
        };

        const buildTextPopover = () => {
            currentTool = "text";
            log("ACTION: text");

            const textResult = clone(".desktop-text-tools");
            const editorResult = clone("#desktop-text-editor", { unhide: true });
            if (!textResult || !editorResult) return;

            const wrapper = document.createElement("div");
            wrapper.className = "desktop-text-popover-content";

            const textNode = textResult.node;
            // clone() strips IDs to avoid duplicate IDs in the DOM.
            const input = textNode.querySelector('.desktop-text-tools__row input[type="text"]');
            const add = textNode.querySelector(".desktop-text-tools__row button");

            const editorNode = editorResult.node;
            const editInput = editorNode.querySelector('.desktop-text-editor > input[type="text"]');
            const ranges = editorNode.querySelectorAll('.text-style-range input[type="range"]');
            const outputs = editorNode.querySelectorAll(".text-style-range output");
            const sizeRange = ranges[0];
            const sizeValue = outputs[0];
            const curveRange = ranges[1];
            const spacingRange = ranges[2];

            const submit = () => {
                const value = input?.value?.trim();
                if (!value) {
                    input?.focus();
                    return;
                }

                const sourceColor = Array.from(editorNode.querySelectorAll("[data-text-color].is-active"))
                    .find(item => item.dataset.textColor)?.dataset.textColor
                    || Array.from(document.querySelectorAll("[data-text-color].is-active"))
                        .find(item => item.dataset.textColor)?.dataset.textColor
                    || "#ffffff";
                const style = {
                    preset: Array.from(editorNode.querySelectorAll("[data-text-style].is-active"))
                        .find(item => item.dataset.textStyle)?.dataset.textStyle || "modern",
                    fontSize: Number(sizeRange?.value || 100),
                    curve: Number(curveRange?.value || 0),
                    letterSpacing: Number(spacingRange?.value || 0),
                };

                log("TEXT ADD", { value, style, color: sourceColor });

                // In the desktop cloned popover the original hidden form is not
                // the active UI. Add directly through the 3D API so the new text
                // layer is created immediately, then fall back to the event bridge
                // for older/customizer builds.
                let added = false;
                if (window.BabaeiCustomizer3D?.isReady?.() && window.BabaeiCustomizer3D?.addText) {
                    added = Boolean(window.BabaeiCustomizer3D.addText(value, style, sourceColor));
                    log("TEXT ADD RESULT", { added, via: "BabaeiCustomizer3D" });
                }

                if (!added) {
                    log("TEXT ADD FALLBACK", { via: "babaei:add-text" });
                    dispatch("babaei:add-text", { text: value, style, color: sourceColor });
                }

                if (input) input.value = "";
                input?.focus();
            };

            add?.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();
                submit();
            });

            input?.addEventListener("keydown", event => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    submit();
                }
            });

            // The editor is shown immediately, so the first click on Aa
            // opens both adding and editing controls in one place.
            wireTextEditor(editorResult);

            wrapper.append(textNode);
            const separator = document.createElement("div");
            separator.className = "desktop-text-popover__separator";
            wrapper.append(separator, editorNode);

            const syncSelection = event => {
                const detail = event.detail || {};
                if (!detail.isText) return;

                if (editInput) editInput.value = String(detail.text || "");
                const style = detail.textStyle || {};
                if (sizeRange) {
                    sizeRange.value = String(style.fontSize ?? 100);
                    if (sizeValue) sizeValue.textContent = String(style.fontSize ?? 100);
                }
                if (curveRange) curveRange.value = String(style.curve ?? 0);
                if (spacingRange) spacingRange.value = String(style.letterSpacing ?? 0);
                if (outputs[1]) outputs[1].textContent = String(style.curve ?? 0);
                if (outputs[2]) outputs[2].textContent = String(style.letterSpacing ?? 0);

                editorNode.querySelectorAll("[data-text-style]").forEach(button => {
                    button.classList.toggle("is-active", button.dataset.textStyle === (style.preset || "modern"));
                });
                if (detail.color) {
                    editorNode.querySelectorAll("[data-text-color]").forEach(button => {
                        button.classList.toggle("is-active", button.dataset.textColor === detail.color);
                    });
                }
            };

            document.addEventListener("babaei:selection-changed", syncSelection);
            const originalClose = close;
            open("متن و استایل", wrapper);

            // Keep the editor usable even when no text is selected yet.
            editorNode.querySelector("#desktop-text-apply")?.addEventListener("click", () => {
                if (!document.getElementById("desktop-text-editor")) return;
            });

            input?.focus();

            // Replace the temporary listener when this popover closes.
            const closeButton = popover.querySelector(".desktop-tool-popover__close");
            closeButton?.addEventListener("click", () => {
                document.removeEventListener("babaei:selection-changed", syncSelection);
            }, { once: true });
        };
        const openGarmentTypes = () => {
            currentTool = "garment";
            log("ACTION: garment type");

            const wrapper = document.createElement("div");
            wrapper.className = "garment-type-popover";

            const options = [
                {
                    key: "tshirt",
                    title: "تیشرت",
                    subtitle: "آستین کوتاه",
                    icon: "👕",
                },
            ];

            const current = window.BabaeiCustomizer3D?.getGarmentType?.() || "tshirt";
            wrapper.innerHTML = options.map(option => `
                <button type="button" class="garment-type-card${option.key === current ? " is-active" : ""}" data-garment-type="${option.key}">
                    <span class="garment-type-card__icon" aria-hidden="true">${option.icon}</span>
                    <span class="garment-type-card__copy">
                        <strong>${option.title}</strong>
                        <small>${option.subtitle}</small>
                    </span>
                    <span class="garment-type-card__check" aria-hidden="true">✓</span>
                </button>
            `).join("");

            wrapper.querySelectorAll("[data-garment-type]").forEach(button => {
                button.addEventListener("click", async event => {
                    event.preventDefault();
                    event.stopPropagation();

                    const type = button.dataset.garmentType;
                    const changed = await window.BabaeiCustomizer3D?.setGarmentType?.(type);
                    if (!changed) return;

                    wrapper.querySelectorAll("[data-garment-type]").forEach(item => {
                        item.classList.toggle("is-active", item === button);
                    });
                });
            });

            open("نوع لباس", wrapper);
        };

        const openShirtColors = () => {
            currentTool = "shirt-color";
            log("ACTION: shirt-color");

            const result = clone("#variant-color-list-right");
            if (!result) return;

            const wrapper = result.node;
            // Forward the desktop palette to the real variant buttons.
            // Do not call setShirtColor() directly here: that only changes the
            // Three.js material and leaves currentVariant stale, which made a
            // later size click silently restore the old color.
            const originals = result.source.querySelectorAll("button[data-color]");
            const buttons = wrapper.querySelectorAll("button[data-color]");

            buttons.forEach((button, index) => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();

                    const original = originals[index];
                    if (!original) return;

                    original.click();
                    buttons.forEach(item => item.classList.remove("is-active"));
                    button.classList.add("is-active");
                });
            });

            const activeOriginal = result.source.querySelector("button.is-active[data-color]");
            if (activeOriginal) {
                wrapper.querySelector(`button[data-color="${CSS.escape(activeOriginal.dataset.color || "")}"]`)
                    ?.classList.add("is-active");
            }

            open("رنگ تیشرت", wrapper);
        };

        const openText = () => buildTextPopover();

        const openTextFont = () => buildTextPopover();

        const openTextColor = () => {
            currentTool = "text-color";
            log("ACTION: text-color");
            const result = clone(".text-style-colors");
            if (!result) return;

            const originals = result.source.querySelectorAll("[data-text-color]");
            result.node.querySelectorAll("[data-text-color]").forEach((button, index) => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    originals[index]?.click();
                });
            });

            open("رنگ متن", result.node);
        };

        const openLabelTools = () => {
            currentTool = "label-tools";
            log("ACTION: label-tools");
            const result = clone("#selected-controls", { unhide: true });
            if (!result) return;

            const originals = result.source.querySelectorAll("[data-action]");
            result.node.querySelectorAll("[data-action]").forEach((button, index) => {
                button.addEventListener("click", event => {
                    event.preventDefault();
                    event.stopPropagation();
                    originals[index]?.click();
                });
            });

            leftPopover.innerHTML = "";
            const title = document.createElement("div");
            title.className = "desktop-tool-popover__title";
            const titleText = document.createElement("span");
            titleText.textContent = "ابزارهای لیبل";
            title.append(titleText);
            leftPopover.append(title, result.node);
            leftPopover.hidden = false;
            log("LEFT LABEL TOOLS OPEN", {
                hidden: leftPopover.hidden,
                display: getComputedStyle(leftPopover).display,
            });
        };

        document.addEventListener("babaei:selection-changed", event => {
            const selected = Boolean(event.detail?.selected);
            if (selected) {
                openLabelTools();
            }
            // Keep the desktop selected-item tools visible even when nothing is selected.
            // The controls themselves remain disabled/empty until a layer is selected.
        });

        const buttons = dock.querySelectorAll("[data-desktop-tool]");

        log("BIND BUTTONS", {
            count: buttons.length,
            tools: Array.from(buttons).map(button => button.dataset.desktopTool),
        });

        buttons.forEach(button => {
            button.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();

                const tool = button.dataset.desktopTool;

                log("CLICK", {
                    tool,
                    title: button.title,
                    target: event.target?.tagName,
                    buttonRect: button.getBoundingClientRect().toJSON(),
                });

                try {
                    if (tool === "label") openLabel();
                    else if (tool === "text") openText();
                    else if (tool === "shirt-color") openShirtColors();
                    else if (tool === "garment") openGarmentTypes();
                    else if (tool === "size") openButtons("#premium-size-list", "انتخاب سایز");
                    else if (tool === "text-font") openTextFont();
                    else if (tool === "label-tools") openLabelTools();
                    else if (tool === "save") {
                        const save = document.getElementById("add-to-cart-design");
                        log("SAVE TARGET", { found: !!save });
                        save?.click();
                    } else {
                        warn("UNKNOWN TOOL", tool);
                    }
                } catch (err) {
                    error("CLICK HANDLER ERROR", { tool, error: err });
                    console.error(err);
                }
            });
        });

        // Desktop popovers are intentionally modal-like: they stay open until
        // the explicit × button is pressed or another desktop tool replaces them.
        document.addEventListener("keydown", event => {
            if (event.key !== "Escape" || popover.hidden) return;
            log("ESCAPE IGNORED: close with ×");
        });

        window.BabaeiDesktopToolsDebug = {
            version: "20260928-garment-type1",
            dock,
            popover,
            buttons,
            inspect() {
                const state = {
                    width: window.innerWidth,
                    dockExists: !!document.getElementById("desktop-tool-dock"),
                    popoverExists: !!document.getElementById("desktop-tool-popover"),
                    dockDisplay: getComputedStyle(dock).display,
                    dockPointerEvents: getComputedStyle(dock).pointerEvents,
                    dockZIndex: getComputedStyle(dock).zIndex,
                    popoverHidden: popover.hidden,
                    popoverDisplay: getComputedStyle(popover).display,
                    popoverPointerEvents: getComputedStyle(popover).pointerEvents,
                    popoverZIndex: getComputedStyle(popover).zIndex,
                };
                console.table(state);
                return state;
            },
        };

        // Desktop selected-item tools stay visible on the left; they are the direct editing surface.
        if (window.innerWidth >= 821) {
            openLabelTools();
        }

        log("READY: desktop tools fully bound");
        log("DEBUG: run BabaeiDesktopToolsDebug.inspect() in console");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initDesktopToolDock, { once: true });
    } else {
        initDesktopToolDock();
    }
})();
