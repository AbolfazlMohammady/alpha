(() => {
    "use strict";

    const root = document.getElementById("user-editor");
    if (!root) return;

    const $$ = (selector, scope = root) => [...scope.querySelectorAll(selector)];

    function syncCustomSelect(select) {
        const wrap = select?.closest(".cc-select-wrap");
        if (!wrap) return;

        const trigger = wrap.querySelector(".cc-select-trigger");
        const menu = wrap.querySelector(".cc-select-menu");
        if (!trigger || !menu) return;

        const selected = select.options[select.selectedIndex];
        trigger.textContent = selected?.textContent?.trim() || "انتخاب کنید";
        menu.innerHTML = "";

        [...select.options].forEach(option => {
            const item = document.createElement("button");
            item.type = "button";
            item.className =
                "cc-select-option" +
                (option.value === select.value ? " is-selected" : "");
            item.textContent = option.textContent;

            item.addEventListener("click", event => {
                event.preventDefault();
                event.stopPropagation();

                select.value = option.value;
                select.dispatchEvent(new Event("change", { bubbles: true }));
                syncCustomSelect(select);
                wrap.classList.remove("is-open");
            });

            menu.appendChild(item);
        });
    }

    function enhanceSelect(select) {
        if (!select || select.dataset.customized === "1") return;

        select.dataset.customized = "1";

        const wrap = document.createElement("div");
        wrap.className = "cc-select-wrap";

        select.parentNode.insertBefore(wrap, select);
        wrap.appendChild(select);

        const trigger = document.createElement("button");
        trigger.type = "button";
        trigger.className = "cc-select-trigger";
        trigger.setAttribute("aria-haspopup", "listbox");
        trigger.setAttribute("aria-expanded", "false");

        const menu = document.createElement("div");
        menu.className = "cc-select-menu";
        menu.setAttribute("role", "listbox");

        wrap.append(trigger, menu);

        trigger.addEventListener("click", event => {
            event.preventDefault();
            event.stopPropagation();

            $$(".cc-select-wrap.is-open").forEach(item => {
                if (item !== wrap) {
                    item.classList.remove("is-open");
                    item.querySelector(".cc-select-trigger")?.setAttribute(
                        "aria-expanded",
                        "false"
                    );
                }
            });

            const open = wrap.classList.toggle("is-open");
            trigger.setAttribute("aria-expanded", String(open));
        });

        select.addEventListener("change", () => {
            syncCustomSelect(select);
            trigger.setAttribute("aria-expanded", "false");
        });

        syncCustomSelect(select);
    }

    function normalizeDigits(value) {
        return String(value || "").replace(/[۰-۹]/g, digit => "۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
    }

    function toLocalIranPhone(value) {
        let phone = normalizeDigits(value)
            .replace(/[^0-9+]/g, "");

        if (phone.startsWith("+98")) {
            phone = "0" + phone.slice(3);
        } else if (phone.startsWith("0098")) {
            phone = "0" + phone.slice(4);
        } else if (phone.startsWith("98") && phone.length >= 11) {
            phone = "0" + phone.slice(2);
        }

        if (phone && !phone.startsWith("0") && phone.startsWith("9")) {
            phone = "0" + phone;
        }

        return phone.slice(0, 11);
    }

    function toE164IranPhone(value) {
        const phone = toLocalIranPhone(value);
        if (/^09\d{9}$/.test(phone)) {
            return "+98" + phone.slice(1);
        }
        return phone;
    }

    const phone = root.querySelector("#id_phone");

    if (phone) {
        // Existing users are shown in the familiar Iranian national format,
        // while the submitted value is always converted to +98/E.164.
        phone.value = toLocalIranPhone(phone.value);

        phone.addEventListener("input", () => {
            const local = toLocalIranPhone(phone.value);
            if (phone.value !== local) phone.value = local;
        });

        phone.addEventListener("blur", () => {
            phone.value = toLocalIranPhone(phone.value);
        });

        root.addEventListener("submit", () => {
            phone.value = toE164IranPhone(phone.value);
        });
    }

    // Match the product editor: role and gender use the same custom dropdown UI.
    $$("select.cc-input").forEach(enhanceSelect);

    document.addEventListener("click", event => {
        if (!event.target.closest("#user-editor .cc-select-wrap")) {
            $$(".cc-select-wrap.is-open").forEach(wrap => {
                wrap.classList.remove("is-open");
                wrap.querySelector(".cc-select-trigger")?.setAttribute(
                    "aria-expanded",
                    "false"
                );
            });
        }
    });

    root.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;

        $$(".cc-select-wrap.is-open").forEach(wrap => {
            wrap.classList.remove("is-open");
            wrap.querySelector(".cc-select-trigger")?.setAttribute(
                "aria-expanded",
                "false"
            );
        });
    });
})();
