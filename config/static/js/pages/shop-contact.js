(() => {
    "use strict";

    const root = document.getElementById("about-globe");
    if (!root) return;

    const D3_URL = "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js";
    const TOPOJSON_URL = "https://cdn.jsdelivr.net/npm/topojson-client@3/dist/topojson-client.min.js";
    const WORLD_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";
    const FRAME_INTERVAL = 1000 / 30;

    let d3 = null;
    let width = 0;
    let height = 0;
    let rotation = [0, -8];
    let dragging = false;
    let lastPoint = null;
    let inView = false;
    let nearView = false;
    let pageVisible = !document.hidden;
    let initialized = false;
    let loading = false;
    let frame = null;
    let animationTimer = null;
    let lastFrameAt = 0;
    let dragFrame = null;
    let pendingRotation = null;
    let worldData = null;

    let svg;
    let countriesLayer;
    let sphereLayer;
    let graticuleLayer;
    let projection;
    let path;
    let graticule;

    function loadScript(src) {
        return new Promise((resolve, reject) => {
            const existing = document.querySelector(`script[src="${src}"]`);
            if (existing) {
                if (existing.dataset.loaded === "true") {
                    resolve();
                    return;
                }
                existing.addEventListener("load", () => resolve(), { once: true });
                existing.addEventListener("error", reject, { once: true });
                return;
            }

            const script = document.createElement("script");
            script.src = src;
            script.async = true;
            script.onload = () => {
                script.dataset.loaded = "true";
                resolve();
            };
            script.onerror = () => reject(new Error(`Failed to load ${src}`));
            document.head.appendChild(script);
        });
    }

    function isAnimationActive() {
        return initialized && inView && pageVisible && !document.hidden && !dragging;
    }

    function stopAnimation() {
        if (animationTimer) {
            clearTimeout(animationTimer);
            animationTimer = null;
        }
        if (frame) {
            cancelAnimationFrame(frame);
            frame = null;
        }
    }

    function scheduleAnimation() {
        if (!isAnimationActive() || frame || animationTimer) return;
        animationTimer = setTimeout(() => {
            animationTimer = null;
            if (!isAnimationActive()) return;
            frame = requestAnimationFrame(animate);
        }, FRAME_INTERVAL);
    }

    function animate(now) {
        frame = null;
        if (!isAnimationActive()) return;

        if (now - lastFrameAt >= FRAME_INTERVAL) {
            lastFrameAt = now;
            rotation = [(rotation[0] + 0.30) % 360, rotation[1]];
            draw();
        }

        scheduleAnimation();
    }

    function resize() {
        if (!initialized) return;

        const rect = root.getBoundingClientRect();
        width = Math.max(260, Math.round(rect.width));
        height = Math.max(220, Math.round(rect.height));

        svg
            .attr("viewBox", `0 0 ${width} ${height}`)
            .attr("width", width)
            .attr("height", height);

        projection
            .translate([width / 2, height * 0.43])
            .scale(Math.min(width, height) * 0.42)
            .rotate(rotation);

        draw();
    }

    function draw() {
        if (!initialized || !width || !height) return;

        projection.rotate(rotation);

        graticuleLayer.attr("d", path(graticule()));
        sphereLayer.attr("d", path({ type: "Sphere" }));

        if (!worldData) return;

        countriesLayer
            .selectAll("path")
            .attr("d", path);
    }

    function pointerPosition(event) {
        const rect = svg.node().getBoundingClientRect();
        return [event.clientX - rect.left, event.clientY - rect.top];
    }

    function stopDrag(event) {
        dragging = false;
        lastPoint = null;
        pendingRotation = null;

        if (dragFrame) {
            cancelAnimationFrame(dragFrame);
            dragFrame = null;
        }

        try {
            svg.node().releasePointerCapture?.(event.pointerId);
        } catch (_) {}

        svg.style("cursor", "grab");
        scheduleAnimation();
    }

    function renderDragFrame() {
        dragFrame = null;
        if (!dragging || !pendingRotation) return;

        rotation = pendingRotation;
        pendingRotation = null;
        draw();
    }

    function bindPointerEvents() {
        svg.on("pointerdown", (event) => {
            dragging = true;
            stopAnimation();
            lastPoint = pointerPosition(event);

            try {
                svg.node().setPointerCapture?.(event.pointerId);
            } catch (_) {}

            svg.style("cursor", "grabbing");
        });

        svg.on("pointermove", (event) => {
            if (!dragging || !lastPoint) return;

            const current = pointerPosition(event);
            const dx = current[0] - lastPoint[0];
            const dy = current[1] - lastPoint[1];

            if (!pendingRotation) {
                pendingRotation = [rotation[0], rotation[1]];
            }

            pendingRotation[0] += dx * 0.35;
            pendingRotation[1] = Math.max(
                -75,
                Math.min(75, pendingRotation[1] - dy * 0.2)
            );

            lastPoint = current;

            if (!dragFrame) {
                dragFrame = requestAnimationFrame(renderDragFrame);
            }
        });

        svg.on("pointerup", stopDrag);
        svg.on("pointercancel", stopDrag);
    }

    function initialize(d3Instance) {
        if (initialized) return;

        d3 = d3Instance;
        svg = d3.select(root)
            .append("svg")
            .attr("role", "img")
            .attr("aria-label", "نقشه چرخان جهان");

        const scene = svg.append("g");
        graticuleLayer = scene.append("path")
            .attr("fill", "none")
            .attr("stroke", "currentColor")
            .attr("stroke-width", 0.55)
            .attr("opacity", 0.14);

        countriesLayer = scene.append("g");

        sphereLayer = scene.append("path")
            .attr("fill", "none")
            .attr("stroke", "currentColor")
            .attr("stroke-width", 1)
            .attr("opacity", 0.55);

        projection = d3.geoOrthographic().precision(0.2);
        path = d3.geoPath(projection);
        graticule = d3.geoGraticule().step([20, 20]);

        initialized = true;
        bindPointerEvents();
        resize();
    }

    async function ensureLoaded() {
        if (loading || initialized || !nearView) return;
        loading = true;

        try {
            if (!window.d3) {
                await loadScript(D3_URL);
            }
            await loadScript(TOPOJSON_URL);

            if (!window.d3 || !window.topojson) {
                throw new Error("Globe dependencies are unavailable");
            }

            initialize(window.d3);

            const response = await fetch(WORLD_URL, {
                credentials: "omit",
                cache: "force-cache",
            });
            if (!response.ok) {
                throw new Error("World map request failed");
            }

            const world = await response.json();
            worldData = window.topojson
                .feature(world, world.objects.countries)
                .features;

            countriesLayer
                .selectAll("path")
                .data(worldData)
                .join("path")
                .attr("d", path)
                .attr("fill", "none")
                .attr("stroke", "currentColor")
                .attr("stroke-width", 0.6)
                .attr("opacity", 0.66);

            draw();
            scheduleAnimation();
        } catch (error) {
            console.error("BABAEI globe:", error);
        } finally {
            loading = false;
        }
    }

    const nearObserver = new IntersectionObserver(
        (entries) => {
            nearView = entries[0]?.isIntersecting ?? false;
            if (nearView) ensureLoaded();
        },
        { rootMargin: "320px 0px", threshold: 0 }
    );

    const visibilityObserver = new IntersectionObserver(
        (entries) => {
            inView = entries[0]?.isIntersecting ?? false;

            if (inView) {
                resize();
                scheduleAnimation();
            } else {
                stopAnimation();
            }
        },
        { threshold: 0.08 }
    );

    nearObserver.observe(root);
    visibilityObserver.observe(root);

    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(root);

    const handleVisibilityChange = () => {
        pageVisible = !document.hidden;
        if (pageVisible && inView) {
            scheduleAnimation();
        } else {
            stopAnimation();
        }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    window.addEventListener("pagehide", () => {
        stopAnimation();
        if (dragFrame) cancelAnimationFrame(dragFrame);
        nearObserver.disconnect();
        visibilityObserver.disconnect();
        resizeObserver.disconnect();
        document.removeEventListener("visibilitychange", handleVisibilityChange);
    }, { once: true });
})();
