(() => {
    const initializedCards = new WeakSet();
    const visibleCards = new WeakSet();

    const cardObserver = "IntersectionObserver" in window
        ? new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    visibleCards.add(entry.target);
                    entry.target.dispatchEvent(new CustomEvent("card:visible"));
                } else {
                    visibleCards.delete(entry.target);
                    entry.target.dispatchEvent(new CustomEvent("card:hidden"));
                }
            });
        }, { rootMargin: "200px 0px", threshold: 0.01 })
        : null;

    const initializeCard = (card) => {
        if (initializedCards.has(card)) return;
        initializedCards.add(card);

        cardObserver?.observe(card);

        const slides = Array.from(card.querySelectorAll("[data-card-slide]"));
        const dots = Array.from(card.querySelectorAll("[data-card-dot]"));
        const favorite = card.querySelector("[data-favorite-button]");
        const media = card.querySelector(".product-card__media, .shop-reference__media");

        if (slides.length > 1) {
            let current = Math.max(0, slides.findIndex((slide) => slide.classList.contains("is-active")));
            let timer = null;
            let startX = null;

            const show = (index, animate = true) => {
                current = (index + slides.length) % slides.length;
                slides.forEach((slide, i) => {
                    slide.classList.toggle("is-active", i === current);
                    if (!animate) slide.style.transition = "none";
                });
                dots.forEach((dot, i) => dot.classList.toggle("is-active", i === current));

                if (!animate) {
                    requestAnimationFrame(() => {
                        slides.forEach((slide) => { slide.style.transition = ""; });
                    });
                }
            };

            const next = () => show(current + 1);

            const stop = () => {
                if (timer) {
                    clearInterval(timer);
                    timer = null;
                }
            };

            const start = () => {
                if ((cardObserver && !visibleCards.has(card)) || document.hidden) return;
                stop();
                timer = setInterval(next, 4200);
            };

            media?.addEventListener("mouseenter", stop);
            media?.addEventListener("mouseleave", start);
            card.addEventListener("card:visible", start);
            card.addEventListener("card:hidden", stop);

            media?.addEventListener("touchstart", (event) => {
                startX = event.touches[0].clientX;
                stop();
            }, { passive: true });

            media?.addEventListener("touchend", (event) => {
                if (startX !== null) {
                    const delta = event.changedTouches[0].clientX - startX;
                    if (Math.abs(delta) > 35) show(current + (delta < 0 ? 1 : -1));
                }
                startX = null;
                start();
            }, { passive: true });

            dots.forEach((dot, i) => {
                dot.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    show(i);
                    start();
                });
            });

            start();
        }

        favorite?.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopPropagation();

            if (favorite.dataset.loading === "1") return;
            const form = favorite.closest("form");
            if (!form) return;

            favorite.dataset.loading = "1";
            favorite.disabled = true;
            favorite.classList.remove("is-popping");
            void favorite.offsetWidth;
            favorite.classList.add("is-popping");

            try {
                const response = await fetch(form.action, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": form.querySelector("[name='csrfmiddlewaretoken']")?.value || "",
                        "X-Requested-With": "XMLHttpRequest",
                        "Accept": "application/json",
                    },
                    credentials: "same-origin",
                    body: new FormData(form),
                });

                const result = await response.json();

                if (response.status === 401 || result.login_required) {
                    window.location.href = result.login_url || "/login/";
                    return;
                }

                if (!response.ok || !result.ok) {
                    throw new Error(result.error || "عملیات انجام نشد.");
                }

                favorite.classList.toggle("is-active", !!result.is_favorite);
                favorite.setAttribute(
                    "aria-label",
                    result.is_favorite ? "حذف از علاقه‌مندی‌ها" : "افزودن به علاقه‌مندی‌ها"
                );
            } catch (error) {
                console.error("Favorite toggle failed:", error);
            } finally {
                favorite.disabled = false;
                favorite.dataset.loading = "0";
            }
        });

        card.querySelectorAll(".product-card__cart").forEach((button) => {
            button.addEventListener("click", (event) => event.stopPropagation());
        });
    };

    const initializeCards = (scope = document) => {
        scope.querySelectorAll?.("[data-product-card]").forEach(initializeCard);
    };

    document.addEventListener("visibilitychange", () => {
        document.querySelectorAll("[data-product-card]").forEach((card) => {
            card.dispatchEvent(new CustomEvent(document.hidden ? "card:hidden" : "card:visible"));
        });
    });

    window.addEventListener("shop:catalog-updated", () => {
        initializeCards(document.querySelector(".shop-reference__catalog") || document);
    });

    initializeCards();
})();
