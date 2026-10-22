(() => {
    const clamp = (value, min = 0, max = 1) => Math.min(max, Math.max(min, value));

    const setupReveal = () => {
        const elements = [...document.querySelectorAll("[data-reveal]")];
        if (!elements.length) return;

        elements.forEach((element, index) => {
            element.classList.add("storefront-reveal");
            element.style.transitionDelay = `${Math.min(index % 5, 4) * 70}ms`;
        });

        if (!("IntersectionObserver" in window)) {
            elements.forEach((element) => element.classList.add("is-visible"));
            return;
        }

        const observer = new IntersectionObserver((entries, currentObserver) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                entry.target.classList.add("is-visible");
                currentObserver.unobserve(entry.target);
            });
        }, { threshold: 0.12, rootMargin: "0px 0px -7% 0px" });

        elements.forEach((element) => observer.observe(element));
    };

    const setupHeaderState = () => {
        const header = document.querySelector(".home-page .site-header");
        if (!header) return;

        const update = () => header.classList.toggle("is-scrolled", window.scrollY > 36);
        update();
        window.addEventListener("scroll", update, { passive: true });
    };

    const setupLabelStory = () => {
        const story = document.querySelector("[data-label-story]");
        const label = story?.querySelector("[data-label-piece]");
        const scene = story?.querySelector(".label-story__scene");
        const target = story?.querySelector(".label-story__target");
        if (!story || !label || !scene || !target) return;

        let ticking = false;
        let metrics = null;
        const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

        const measure = () => {
            const storyRect = story.getBoundingClientRect();
            const sceneRect = scene.getBoundingClientRect();
            const targetRect = target.getBoundingClientRect();
            const labelWidth = label.offsetWidth;
            const labelHeight = label.offsetHeight;
            const finalX = targetRect.left - sceneRect.left + (targetRect.width - labelWidth) / 2;
            const finalY = targetRect.top - sceneRect.top + (targetRect.height - labelHeight) / 2;
            const startScroll = storyRect.top + window.scrollY - window.innerHeight * 0.18;
            const endScroll = storyRect.top + window.scrollY + story.offsetHeight - window.innerHeight * 0.84;
            metrics = {
                startScroll,
                travel: Math.max(window.innerHeight * 0.72, endScroll - startScroll),
                finalX,
                finalY,
                startX: (window.innerWidth <= 560 ? -sceneRect.width * 0.52 : -sceneRect.width * 0.44),
                startY: finalY - sceneRect.height * (window.innerWidth <= 560 ? 0.13 : 0.16),
            };
        };

        const update = () => {
            ticking = false;
            if (!metrics) measure();
            const progress = reduceMotion ? 1 : clamp((window.scrollY - metrics.startScroll) / metrics.travel);
            const x = metrics.startX + (metrics.finalX - metrics.startX) * progress;
            const y = metrics.startY + (metrics.finalY - metrics.startY) * progress;
            const rotation = -13 * (1 - progress);
            const scale = 0.84 + progress * 0.16;
            story.style.setProperty("--story-progress", progress.toFixed(3));
            story.style.setProperty("--target-opacity", clamp((0.78 - progress) * 2.2).toFixed(3));
            story.style.setProperty("--garment-scale", (1 + progress * 0.025).toFixed(3));
            label.style.transform = `translate3d(${x}px, ${y}px, 0) rotate(${rotation}deg) scale(${scale})`;
        };

        const requestUpdate = () => {
            if (ticking) return;
            ticking = true;
            window.requestAnimationFrame(update);
        };

        measure();
        update();
        if (!reduceMotion) window.addEventListener("scroll", requestUpdate, { passive: true });
        window.addEventListener("resize", () => { measure(); requestUpdate(); }, { passive: true });
    };

    const setupProductGallery = () => {
        document.querySelectorAll("[data-product-gallery]").forEach((gallery) => {
            const main = gallery.querySelector("#product-gallery-main");
            const index = gallery.querySelector("[data-gallery-index]");
            const thumbs = [...gallery.querySelectorAll("[data-gallery-thumb]")];
            if (!main || !thumbs.length) return;

            /* The main shot is wrapped in <picture> so AVIF/WebP can be served.
               A matching <source> outranks img.src, so swapping only the img
               would leave the first frame on screen. Each thumb therefore
               carries the derivative srcsets the template already rendered
               (data-avif / data-webp) and both are swapped together. When the
               generator has not run those attributes are empty and only
               img.src changes, exactly like before. */
            const picture = main.parentElement && main.parentElement.tagName === "PICTURE"
                ? main.parentElement
                : null;
            const sources = picture ? [...picture.querySelectorAll("source[data-format]")] : [];

            /* Selecting a thumb swaps the derivative srcsets and the plain src
               together, moves the rail's active row and updates the position
               counter. Both <source> elements must move with img.src, otherwise
               the still-matching AVIF/WebP source keeps the previous frame on
               screen. */
            const select = (thumb, thumbIndex) => {
                const source = thumb.dataset.image;
                if (!source) return;
                const avif = thumb.dataset.avif || "";
                const webp = thumb.dataset.webp || "";
                main.style.opacity = "0";
                window.setTimeout(() => {
                    sources.forEach((element) => {
                        const next = element.dataset.format === "avif" ? avif : webp;
                        if (next) element.setAttribute("srcset", next);
                        else element.removeAttribute("srcset");
                    });
                    main.src = source;
                    if (thumb.dataset.alt) main.alt = thumb.dataset.alt;
                    main.style.opacity = "";
                }, 140);
                thumbs.forEach((item, itemIndex) => {
                    const active = itemIndex === thumbIndex;
                    item.classList.toggle("is-active", active);
                    item.setAttribute("aria-selected", active ? "true" : "false");
                });
                if (index) index.textContent = String(thumbIndex + 1).padStart(2, "0");
            };

            thumbs.forEach((thumb, thumbIndex) => {
                thumb.addEventListener("click", () => select(thumb, thumbIndex));
            });
        });
    };

    const init = () => {
        setupReveal();
        setupHeaderState();
        setupLabelStory();
        setupProductGallery();
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
