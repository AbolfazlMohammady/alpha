(() => {
    const data = window.BabaeiProduct || {};
    const variants = Array.isArray(data.variants) ? data.variants : [];
    const cartVariants = data.cartVariants && typeof data.cartVariants === "object" ? data.cartVariants : {};
    const colorButtons = [...document.querySelectorAll(".color-option")];
    const sizeButtons = [...document.querySelectorAll(".size-option")];
    const priceEl = document.getElementById("product-price");
    const oldPriceRow = document.getElementById("product-old-price-row");
    const oldPriceEl = document.getElementById("product-old-price");
    const discountEl = document.getElementById("product-discount");
    const totalStockEl = document.getElementById("total-stock");
    const statusEl = document.getElementById("variant-status");
    const selectedColorLabel = document.getElementById("selected-color-label");
    const selectedSizeLabel = document.getElementById("selected-size-label");
    const variantInput = document.getElementById("cart-variant-id");
    const addButton = document.getElementById("add-to-cart-button");
    const inCartLink = document.getElementById("product-in-cart");
    const inCartQuantity = document.querySelector("[data-product-in-cart-quantity]");
    const addForm = document.getElementById("add-to-cart-form");
    const quantityWrap = document.querySelector("[data-product-quantity-wrap]");
    const quantityInput = document.getElementById("cart-quantity");
    const quantityButtons = [...document.querySelectorAll("[data-product-quantity-button]")];
    const quantityStock = document.querySelector("[data-product-quantity-stock]");
    const headerBadges = [...document.querySelectorAll(".header-cart__badge")];

    let selectedColorId = null;
    let selectedSizeId = null;
    let currentStock = null;

    const formatPrice = (value) => new Intl.NumberFormat("fa-IR").format(Number(value || 0));
    const formatPercent = (value) => `٪${formatPrice(value)}`;
    const discounted = (variant) => variant && variant.compare_at_price && Number(variant.compare_at_price) > Number(variant.price);
    const discountPercent = (variant) => discounted(variant) ? Math.round(((Number(variant.compare_at_price) - Number(variant.price)) * 100) / Number(variant.compare_at_price)) : 0;
    const availableForColor = (colorId) => variants.filter((variant) => Number(variant.color_id) === Number(colorId));
    const findVariant = () => variants.find((variant) => Number(variant.color_id) === Number(selectedColorId) && Number(variant.size_id) === Number(selectedSizeId));
    const findColorName = (colorId) => (variants.find((item) => Number(item.color_id) === Number(colorId)) || {}).color || "";
    const findSizeName = (sizeId) => (variants.find((item) => Number(item.size_id) === Number(sizeId)) || {}).size || "";
    const cartKeyForVariant = (variant) => variant ? String(variant.id) : "base";
    const cartQuantityForVariant = (variant) => Number(cartVariants[cartKeyForVariant(variant)] || 0);

    const updateQuantityUI = () => {
        if (!quantityInput) return;
        let value = Number.parseInt(quantityInput.value, 10) || 1;
        value = Math.max(1, value);
        if (currentStock !== null) value = Math.min(value, currentStock);
        quantityInput.value = value;
        quantityInput.max = currentStock !== null ? String(currentStock) : "";
        if (quantityStock) quantityStock.textContent = currentStock !== null ? `${formatPrice(currentStock)} عدد موجود` : "";
        quantityButtons.forEach((button) => {
            const delta = Number(button.dataset.productQuantityButton);
            button.disabled = delta < 0 ? value <= 1 : currentStock !== null && value >= currentStock;
        });
    };

    const showToast = (message, isError = false) => {
        const toast = document.createElement("div");
        toast.className = `product-toast${isError ? " product-toast--error" : ""}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add("is-visible"));
        setTimeout(() => { toast.classList.remove("is-visible"); setTimeout(() => toast.remove(), 180); }, 2400);
    };

    const updateHeaderCount = (count) => headerBadges.forEach((badge) => {
        badge.textContent = formatPrice(count);
        badge.classList.toggle("is-hidden", Number(count) === 0);
    });

    const renderSizes = () => sizeButtons.forEach((button) => {
        const sizeId = Number(button.dataset.sizeId);
        const variant = variants.find((item) => Number(item.color_id) === Number(selectedColorId) && Number(item.size_id) === sizeId);
        const available = Boolean(variant && Number(variant.stock) > 0);
        button.disabled = !variant || !available;
        button.classList.toggle("is-unavailable", !variant || !available);
        button.classList.toggle("is-selected", sizeId === Number(selectedSizeId));
    });

    const renderColors = () => colorButtons.forEach((button) => {
        const colorId = Number(button.dataset.colorId);
        const hasStock = availableForColor(colorId).some((variant) => Number(variant.stock) > 0);
        button.disabled = !hasStock;
        button.classList.toggle("is-selected", colorId === Number(selectedColorId));
        button.classList.toggle("is-unavailable", !hasStock);
    });

    const renderCartState = (variant) => {
        const existingQuantity = cartQuantityForVariant(variant);
        const alreadyInCart = existingQuantity > 0;

        if (inCartLink) {
            inCartLink.hidden = !alreadyInCart;
            if (inCartQuantity) inCartQuantity.textContent = `${formatPrice(existingQuantity)} عدد`;
        }
        if (addButton) {
            addButton.hidden = alreadyInCart;
            addButton.textContent = "افزودن به سبد خرید";
            addButton.disabled = alreadyInCart || !variant || Number(variant.stock) <= 0;
        }
        if (quantityWrap) quantityWrap.classList.toggle("is-in-cart", alreadyInCart);
        if (quantityInput) quantityInput.disabled = alreadyInCart;
        if (alreadyInCart) {
            quantityButtons.forEach((button) => { button.disabled = true; });
            if (quantityStock) quantityStock.textContent = `${formatPrice(existingQuantity)} عدد در سبد`;
        } else {
            updateQuantityUI();
        }
    };

    const renderVariant = () => {
        const variant = findVariant();
        if (selectedColorLabel) selectedColorLabel.textContent = findColorName(selectedColorId);
        if (selectedSizeLabel) selectedSizeLabel.textContent = findSizeName(selectedSizeId);

        if (!variant) {
            if (statusEl) statusEl.textContent = "این ترکیب رنگ و سایز موجود نیست.";
            if (priceEl) priceEl.textContent = formatPrice(data.initialProductPrice);
            if (oldPriceRow) oldPriceRow.classList.add("is-hidden");
            if (variantInput) variantInput.value = "";
            currentStock = 0;
            if (addButton) { addButton.hidden = false; addButton.textContent = "افزودن به سبد خرید"; addButton.disabled = true; }
            if (inCartLink) inCartLink.hidden = true;
            if (quantityWrap) quantityWrap.classList.remove("is-in-cart");
            if (quantityInput) quantityInput.disabled = true;
            updateQuantityUI();
            return;
        }

        if (priceEl) priceEl.textContent = formatPrice(variant.price);
        if (discounted(variant)) {
            if (oldPriceEl) oldPriceEl.textContent = formatPrice(variant.compare_at_price);
            if (discountEl) discountEl.textContent = formatPercent(discountPercent(variant));
            oldPriceRow?.classList.remove("is-hidden");
        } else {
            oldPriceRow?.classList.add("is-hidden");
            if (oldPriceEl) oldPriceEl.textContent = "";
            if (discountEl) discountEl.textContent = "";
        }

        if (variantInput) variantInput.value = variant.id;
        currentStock = Number(variant.stock || 0);
        if (statusEl) statusEl.innerHTML = currentStock > 0 ? `<strong>${formatPrice(currentStock)} عدد</strong> از این ترکیب موجود است` : "این ترکیب ناموجود است.";

        const existingQuantity = cartQuantityForVariant(variant);
        if (quantityInput && existingQuantity === 0) quantityInput.value = 1;
        renderCartState(variant);
    };

    const selectInitialVariant = () => {
        if (!variants.length) {
            currentStock = null;
            const existingQuantity = cartQuantityForVariant(null);
            if (quantityInput) quantityInput.disabled = existingQuantity > 0;
            if (quantityWrap) quantityWrap.classList.toggle("is-in-cart", existingQuantity > 0);
            if (addButton) { addButton.hidden = existingQuantity > 0; addButton.disabled = existingQuantity > 0; }
            if (inCartLink) inCartLink.hidden = existingQuantity === 0;
            if (inCartQuantity && existingQuantity) inCartQuantity.textContent = `${formatPrice(existingQuantity)} عدد`;
            updateQuantityUI();
            return;
        }
        const initial = variants.find((variant) => Number(variant.stock) > 0) || variants[0];
        selectedColorId = initial.color_id;
        selectedSizeId = initial.size_id;
        renderColors();
        renderSizes();
        renderVariant();
    };

    colorButtons.forEach((button) => button.addEventListener("click", () => {
        if (button.disabled) return;
        selectedColorId = Number(button.dataset.colorId);
        const sameColor = availableForColor(selectedColorId);
        const nextSize = sameColor.find((variant) => Number(variant.stock) > 0) || sameColor[0];
        selectedSizeId = nextSize ? nextSize.size_id : null;
        renderColors(); renderSizes(); renderVariant();
    }));

    sizeButtons.forEach((button) => button.addEventListener("click", () => {
        if (button.disabled) return;
        selectedSizeId = Number(button.dataset.sizeId);
        renderSizes(); renderVariant();
    }));

    quantityButtons.forEach((button) => button.addEventListener("click", () => {
        if (!quantityInput || button.disabled) return;
        quantityInput.value = (Number.parseInt(quantityInput.value, 10) || 1) + Number(button.dataset.productQuantityButton);
        updateQuantityUI();
    }));
    quantityInput?.addEventListener("input", updateQuantityUI);
    quantityInput?.addEventListener("blur", updateQuantityUI);

    addForm?.addEventListener("submit", async (event) => {
        event.preventDefault();
        const variant = findVariant();
        if (!addButton || addButton.disabled || !variant) return;
        addButton.disabled = true;
        addButton.classList.add("is-loading");
        addButton.textContent = "در حال افزودن...";

        try {
            const response = await fetch(addForm.action, {
                method: "POST",
                headers: { "X-Requested-With": "XMLHttpRequest", "Accept": "application/json" },
                body: new FormData(addForm),
                credentials: "same-origin",
            });
            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) throw new Error(result.message || "افزودن به سبد خرید انجام نشد.");
            updateHeaderCount(result.count);
            cartVariants[cartKeyForVariant(variant)] = Number(result.quantity || quantityInput?.value || 1);
            renderVariant();
            showToast("این مدل به سبد خرید اضافه شد.");
        } catch (error) {
            addButton.hidden = false;
            addButton.disabled = false;
            addButton.textContent = "افزودن به سبد خرید";
            showToast(error.message, true);
        } finally {
            addButton.classList.remove("is-loading");
        }
    });

    if (totalStockEl && variants.length) totalStockEl.textContent = `${formatPrice(variants.reduce((sum, variant) => sum + Number(variant.stock || 0), 0))} عدد`;
    selectInitialVariant();
})();
