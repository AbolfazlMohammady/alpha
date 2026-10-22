(() => {
    const root = document.querySelector(".shop-reference");
    if (!root) return;

    let catalogLoading = false;
    let nextPageLoading = false;
    let infiniteObserver = null;

    const getPanel = () => root.querySelector("[data-shop-filter-panel]");
    const getToggle = () => root.querySelector("[data-shop-filter-toggle]");

    const formatPrice = (value) => Number(value || 0).toLocaleString("fa-IR");

    const syncRange = (source) => {
        const minRange = root.querySelector("[data-min-range]");
        const maxRange = root.querySelector("[data-max-range]");
        const minInput = root.querySelector("[data-min-price-input]");
        const maxInput = root.querySelector("[data-max-price-input]");
        const minLabel = root.querySelector("[data-min-price-label]");
        const maxLabel = root.querySelector("[data-max-price-label]");

        if (!minRange || !maxRange) return;

        const ceiling = Number(maxRange.max || 0);
        let min = Number(minRange.value || 0);
        let max = Number(maxRange.value || ceiling);

        if (min > max) {
            if (source === "min") max = min;
            else min = max;
            minRange.value = String(min);
            maxRange.value = String(max);
        }

        if (minInput) minInput.value = min > 0 ? String(min) : "";
        if (maxInput) maxInput.value = max < ceiling ? String(max) : "";
        if (minLabel) minLabel.textContent = formatPrice(min);
        if (maxLabel) maxLabel.textContent = formatPrice(max);

        // Drive the filled segment of the track from the two handles. The old
        // markup drew a fixed pseudo-element that never moved, so it always
        // looked like the whole range was selected.
        const range = root.querySelector(".shop-reference__range");
        if (range) {
            const span = ceiling > 0 ? ceiling : 1;
            range.style.setProperty("--sh-range-lower", `${(min / span) * 100}%`);
            range.style.setProperty("--sh-range-upper", `${(max / span) * 100}%`);
        }
    };

    const syncFilterCount = (url = window.location.href) => {
        const count = root.querySelector("[data-filter-count]");
        if (!count) return;

        const params = new URL(url, window.location.origin).searchParams;
        const activeFilters = ["category", "size", "min_price", "max_price", "discount"]
            .filter((key) => params.get(key));

        count.textContent = String(activeFilters.length);
        count.style.display = activeFilters.length ? "inline-grid" : "none";
    };

    const setLoading = (loading) => {
        root.classList.toggle("is-filter-loading", loading);
        root.setAttribute("aria-busy", loading ? "true" : "false");
    };

    const closeFilters = () => {
        const panel = getPanel();
        const toggle = getToggle();
        if (!panel) return;
        panel.classList.remove("is-open");
        toggle?.setAttribute("aria-expanded", "false");
    };

    const closeSort = () => {
        const dropdown = root.querySelector("[data-sort-dropdown]");
        const trigger = root.querySelector("[data-sort-trigger]");
        dropdown?.classList.remove("is-open");
        trigger?.setAttribute("aria-expanded", "false");
    };

    const updateUrl = (url, push = true) => {
        if (push) window.history.pushState({shopCatalog: true}, "", url.toString());
    };

    const initializeInfiniteScroll = () => {
        if (infiniteObserver) infiniteObserver.disconnect();

        const sentinel = root.querySelector("[data-shop-infinite-sentinel]");
        if (!sentinel) return;

        infiniteObserver = "IntersectionObserver" in window
            ? new IntersectionObserver((entries) => {
                if (entries.some((entry) => entry.isIntersecting)) loadNextPage();
            }, {rootMargin: "700px 0px 700px", threshold: 0})
            : null;

        if (infiniteObserver) {
            infiniteObserver.observe(sentinel);
        } else {
            sentinel.addEventListener("click", loadNextPage, {once: true});
        }
    };

    const loadNextPage = async () => {
        if (nextPageLoading || catalogLoading) return;

        const pagination = root.querySelector("[data-shop-pagination]");
        const nextLink = pagination?.querySelector('a[aria-label="صفحه بعد"]');
        if (!nextLink) {
            root.querySelector("[data-shop-infinite-sentinel]")?.classList.add("is-done");
            return;
        }

        nextPageLoading = true;
        root.classList.add("is-loading-more");

        try {
            const response = await fetch(nextLink.href, {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "text/html"
                }
            });

            if (!response.ok) throw new Error("Next page request failed");

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const nextCatalog = doc.querySelector(".shop-reference__catalog");
            const currentProducts = root.querySelector("[data-shop-products]");
            const nextProducts = nextCatalog?.querySelector("[data-shop-products]");

            if (!currentProducts || !nextProducts) {
                throw new Error("Next product grid not found");
            }

            nextProducts.querySelectorAll("[data-product-card]").forEach((card) => {
                currentProducts.appendChild(card);
            });

            const currentPagination = root.querySelector("[data-shop-pagination]");
            const nextPagination = nextCatalog.querySelector("[data-shop-pagination]");

            if (currentPagination && nextPagination) {
                currentPagination.replaceWith(nextPagination);
            }

            const currentSentinel = root.querySelector("[data-shop-infinite-sentinel]");
            const nextSentinel = nextCatalog.querySelector("[data-shop-infinite-sentinel]");
            if (!nextPagination?.querySelector('a[aria-label="صفحه بعد"]') && currentSentinel) {
                currentSentinel.classList.add("is-done");
            } else if (currentSentinel) {
                currentSentinel.classList.remove("is-done");
            }

            const stateUrl = new URL(nextLink.href, window.location.href);
            stateUrl.searchParams.delete("page");
            window.history.replaceState(
                {shopCatalog: true},
                "",
                stateUrl.toString()
            );

            window.dispatchEvent(new CustomEvent("shop:catalog-updated"));
            initializeInfiniteScroll();
        } catch (error) {
            console.error("[BABAEI] Infinite shop pagination failed:", error);
        } finally {
            nextPageLoading = false;
            root.classList.remove("is-loading-more");
        }
    };

    const fetchCatalog = async (targetUrl, {push = true, preservePage = false} = {}) => {
        const url = new URL(targetUrl, window.location.href);
        if (!preservePage) url.searchParams.delete("page");

        if (catalogLoading) return;
        catalogLoading = true;
        setLoading(true);

        try {
            const response = await fetch(url.toString(), {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "text/html"
                }
            });

            if (!response.ok) throw new Error("Catalog request failed");

            const html = await response.text();
            const doc = new DOMParser().parseFromString(html, "text/html");
            const nextCatalog = doc.querySelector(".shop-reference__catalog");
            const currentCatalog = root.querySelector(".shop-reference__catalog");

            if (!nextCatalog || !currentCatalog) {
                throw new Error("Catalog markup not found");
            }

            currentCatalog.replaceWith(nextCatalog);

            if (push) updateUrl(url, true);

            if (doc.title) document.title = doc.title;
            syncFilterCount(url.toString());
            closeFilters();
            closeSort();

            window.dispatchEvent(new CustomEvent("shop:catalog-updated"));
            initializeInfiniteScroll();
            syncRange();
        } catch (error) {
            console.error("[BABAEI] Shop filter update failed:", error);
        } finally {
            catalogLoading = false;
            setLoading(false);
        }
    };

    const buildFilterUrl = (form) => {
        const url = new URL(window.location.href);
        const formData = new FormData(form);

        ["size", "min_price", "max_price", "discount"].forEach((key) => {
            url.searchParams.delete(key);
        });

        for (const [key, value] of formData.entries()) {
            if (value !== "") url.searchParams.set(key, value);
        }

        url.searchParams.delete("page");
        return url;
    };

    root.addEventListener("click", (event) => {
        const filterToggle = event.target.closest("[data-shop-filter-toggle]");
        if (filterToggle) {
            const panel = getPanel();
            if (panel?.classList.contains("is-open")) closeFilters();
            else {
                panel?.classList.add("is-open");
                filterToggle.setAttribute("aria-expanded", "true");
            }
            return;
        }

        if (event.target.closest("[data-shop-filter-close]")) {
            closeFilters();
            return;
        }

        const sortTrigger = event.target.closest("[data-sort-trigger]");
        if (sortTrigger) {
            event.preventDefault();
            event.stopPropagation();
            const dropdown = root.querySelector("[data-sort-dropdown]");
            const open = dropdown?.classList.toggle("is-open");
            sortTrigger.setAttribute("aria-expanded", open ? "true" : "false");
            return;
        }

        const sortOption = event.target.closest("[data-sort-option]");
        if (sortOption) {
            event.preventDefault();
            const value = sortOption.dataset.value;
            if (!value) return;

            const url = new URL(window.location.href);
            url.searchParams.set("sort", value);
            url.searchParams.delete("page");
            fetchCatalog(url);
            return;
        }

        const clearLink = event.target.closest(".shop-reference__clear");
        if (clearLink) {
            event.preventDefault();
            fetchCatalog(clearLink.href);
            return;
        }

        const categoryLink = event.target.closest(".shop-reference__category-list a");
        if (categoryLink) {
            const url = new URL(categoryLink.href, window.location.href);
            if (url.pathname === window.location.pathname) {
                event.preventDefault();
                fetchCatalog(url);
                return;
            }
        }
    });

    root.addEventListener("submit", (event) => {
        const form = event.target.closest("[data-shop-filter-form]");
        if (!form) return;

        event.preventDefault();
        syncRange();
        fetchCatalog(buildFilterUrl(form));
    });

    root.addEventListener("input", (event) => {
        if (event.target.matches("[data-min-range]")) syncRange("min");
        if (event.target.matches("[data-max-range]")) syncRange("max");
    });

    root.addEventListener("change", (event) => {
        const input = event.target;
        if (!input.matches(".shop-reference__sizes input, .shop-reference__discount-check input")) return;

        if (input.type === "radio") {
            root.querySelectorAll('input[name="' + input.name + '"]').forEach((item) => {
                item.closest("label")?.classList.toggle("is-active", item.checked);
            });
        } else {
            input.closest("label")?.classList.toggle("is-active", input.checked);
        }
    });

    document.addEventListener("click", (event) => {
        if (!event.target.closest(".shop-reference__sort-section")) closeSort();
    });

    window.addEventListener("popstate", () => {
        fetchCatalog(window.location.href, {
            push: false,
            preservePage: new URL(window.location.href).searchParams.has("page")
        });
    });

    /* Must match the breakpoint where css/pages/shop-catalog.css turns the rail
       into a full-screen sheet, otherwise the class is left behind on resize. */
    const mobileMedia = window.matchMedia("(max-width: 940px)");
    mobileMedia.addEventListener?.("change", () => {
        if (!mobileMedia.matches) closeFilters();
    });

    /* Escape closes whichever overlay is open. Neither the filter sheet nor the
       sort menu could be dismissed from the keyboard before, which left the
       full-screen sheet on a phone with only its × button as an exit. */
    document.addEventListener("keydown", (event) => {
        if (event.key !== "Escape") return;

        let handled = false;
        const panel = getPanel();
        if (panel?.classList.contains("is-open")) {
            closeFilters();
            getToggle()?.focus({ preventScroll: true });
            handled = true;
        }
        const dropdown = root.querySelector("[data-sort-dropdown]");
        if (dropdown?.classList.contains("is-open")) {
            closeSort();
            root.querySelector("[data-sort-trigger]")?.focus({ preventScroll: true });
            handled = true;
        }
        if (handled) event.preventDefault();
    });

    syncRange();
    syncFilterCount();
    initializeInfiniteScroll();
})();
