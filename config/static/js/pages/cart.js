(() => {
    const root = document.querySelector("[data-cart-page]");
    if (!root) return;

    const formatPrice = (value) => new Intl.NumberFormat("fa-IR").format(Number(value || 0));
    const csrfToken = root.querySelector("input[name=csrfmiddlewaretoken]")?.value;
    const summaryCount = root.querySelector("[data-cart-count]");
    const summaryCountValue = Number(summaryCount?.dataset.cartCountValue || 0);
    const subtotalEls = [...root.querySelectorAll("[data-cart-subtotal]")];
    const summary = root.querySelector("[data-cart-summary]");
    const empty = root.querySelector("[data-cart-empty]");
    const headerBadges = [...document.querySelectorAll(".header-cart__badge, .sh-icon__badge")];

    const animateNumber = (element, from, to, duration = 360) => {
        if (!element) return;

        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            element.textContent = formatPrice(to);
            return;
        }

        const start = Number(from || 0);
        const end = Number(to || 0);
        const startedAt = performance.now();
        cancelAnimationFrame(Number(element.dataset.numberFrame || 0));

        const tick = (now) => {
            const progress = Math.min(1, (now - startedAt) / duration);
            const eased = 1 - Math.pow(1 - progress, 3);
            element.textContent = formatPrice(Math.round(start + (end - start) * eased));

            if (progress < 1) {
                element.dataset.numberFrame = String(requestAnimationFrame(tick));
            } else {
                delete element.dataset.numberFrame;
            }
        };

        element.dataset.numberFrame = String(requestAnimationFrame(tick));
    };

    const animateLineTotal = (element, from, to) => {
        if (!element) return;

        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
            element.textContent = formatPrice(to) + " تومان";
            return;
        }

        const start = Number(from || 0);
        const end = Number(to || 0);
        const startedAt = performance.now();
        cancelAnimationFrame(Number(element.dataset.numberFrame || 0));

        const tick = (now) => {
            const progress = Math.min(1, (now - startedAt) / 300);
            const eased = 1 - Math.pow(1 - progress, 3);
            element.textContent = formatPrice(Math.round(start + (end - start) * eased)) + " تومان";

            if (progress < 1) {
                element.dataset.numberFrame = String(requestAnimationFrame(tick));
            } else {
                delete element.dataset.numberFrame;
            }
        };

        element.dataset.numberFrame = String(requestAnimationFrame(tick));
    };

    const updateHeaderCount = (count) => {
        headerBadges.forEach((badge) => {
            badge.textContent = formatPrice(count);
            badge.classList.toggle("is-hidden", Number(count) === 0);
        });
    };

    const setTotals = (count, subtotal, animate = true) => {
        const subtotalEl = subtotalEls[0];
        const previous = Number(subtotalEl?.dataset.cartNumber || subtotal || 0);

        if (summaryCount) summaryCount.textContent = "(" + formatPrice(count) + ")";

        subtotalEls.forEach((el) => {
            if (animate) {
                animateNumber(el, previous, subtotal);
            } else {
                el.textContent = formatPrice(subtotal);
            }
            el.dataset.cartNumber = String(subtotal);
        });

        updateHeaderCount(count);
    };

    const request = async (form) => {
        const response = await fetch(form.action, {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
                ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
            },
            body: new FormData(form),
            credentials: "same-origin",
        });

        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.ok) {
            throw new Error(data.message || "به‌روزرسانی سبد خرید انجام نشد.");
        }
        return data;
    };

    const showMessage = (message, isError = false) => {
        const toast = document.createElement("div");
        toast.className = "cart-toast" + (isError ? " cart-toast--error" : "");
        toast.textContent = message;
        document.body.appendChild(toast);

        requestAnimationFrame(() => toast.classList.add("is-visible"));
        setTimeout(() => {
            toast.classList.remove("is-visible");
            setTimeout(() => toast.remove(), 180);
        }, 2200);
    };

    const syncItem = (itemId, data) => {
        const items = [...root.querySelectorAll("[data-cart-item]")].filter(
            (item) => String(item.dataset.cartId) === String(itemId)
        );

        items.forEach((item) => {
            const quantity = item.querySelector("[data-quantity-value]");
            const lineTotal = item.querySelector("[data-line-total]");
            const minus = item.querySelector("[data-quantity-minus]");
            const plus = item.querySelector("[data-quantity-plus]");
            const max = Number(item.dataset.stock || 0);
            const previousLineTotal = Number(lineTotal?.dataset.lineValue || 0);

            if (quantity) {
                quantity.textContent = formatPrice(data.quantity);
                quantity.dataset.value = String(data.quantity);
            }

            if (lineTotal) {
                animateLineTotal(lineTotal, previousLineTotal, data.line_total);
                lineTotal.dataset.lineValue = String(data.line_total);
            }

            if (minus) minus.disabled = data.quantity <= 1;
            if (plus && max > 0) plus.disabled = data.quantity >= max;
        });
    };

    const removeItem = (itemId) => {
        root.querySelectorAll("[data-cart-item]").forEach((item) => {
            if (String(item.dataset.cartId) !== String(itemId)) return;
            item.classList.add("is-removing");
            setTimeout(() => item.remove(), 180);
        });
    };

    root.addEventListener("submit", async (event) => {
        const form = event.target.closest("form[data-cart-action]");
        if (!form) return;

        event.preventDefault();

        const buttons = [...form.querySelectorAll("button")];
        buttons.forEach((button) => { button.disabled = true; });

        try {
            const data = await request(form);
            const item = form.closest("[data-cart-item]");
            const itemId = item?.dataset.cartId;

            if (form.dataset.cartAction === "update" && itemId) {
                syncItem(itemId, data);
            }

            if (form.dataset.cartAction === "remove" && itemId) {
                removeItem(itemId);
            }

            if (form.dataset.cartAction === "clear") {
                root.querySelectorAll("[data-cart-item]").forEach((el) => {
                    el.classList.add("is-removing");
                    setTimeout(() => el.remove(), 180);
                });
            }

            setTotals(data.count, data.subtotal, true);

            if (Number(data.count) === 0) {
                if (summary) summary.hidden = true;
                if (empty) empty.hidden = false;
                root.querySelector(".cart-checkout-layout")?.remove();
                root.classList.add("is-empty");
            }

            showMessage(data.message || "سبد خرید بروزرسانی شد.");
        } catch (error) {
            showMessage(error.message, true);
        } finally {
            buttons.forEach((button) => { button.disabled = false; });

            if (form.dataset.cartAction === "update") {
                const item = form.closest("[data-cart-item]");
                const quantity = Number(item?.querySelector("[data-quantity-value]")?.dataset.value || 1);
                const minus = item?.querySelector("[data-quantity-minus]");
                const plus = item?.querySelector("[data-quantity-plus]");
                const max = Number(item?.dataset.stock || 0);

                if (minus) minus.disabled = quantity <= 1;
                if (plus && max > 0) plus.disabled = quantity >= max;
            }
        }
    });

    root.addEventListener("click", (event) => {
        const button = event.target.closest("[data-quantity-button]");
        if (!button || button.disabled) return;

        const form = button.closest("form[data-cart-action=update]");
        const item = button.closest("[data-cart-item]");
        if (!form || !item) return;

        event.preventDefault();

        const quantityEl = item.querySelector("[data-quantity-value]");
        const current = Number(quantityEl?.dataset.value || 1);
        const next = current + Number(button.dataset.quantityButton);
        const max = Number(item.dataset.stock || 0);

        if (next < 1 || (max > 0 && next > max)) return;

        form.querySelector("input[name=quantity]").value = next;
        form.requestSubmit();
    });

    const initialCount = summaryCountValue;
    const initialSubtotal = Number(subtotalEls[0]?.dataset.cartNumber || 0);
    setTotals(initialCount, initialSubtotal, false);
})();
