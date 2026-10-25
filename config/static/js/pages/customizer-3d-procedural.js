import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { DecalGeometry } from "three/addons/geometries/DecalGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

(() => {
    "use strict";

    // ================================================================
    // BABAei 3D STUDIO — MOBILE MODEL BASELINE v1.0.0
    // #MODEL-FIXED #MOBILE-FRAME #DO-NOT-REGRESS
    // The GLB loading + base framing is considered stable at this point.
    // Future mobile UI changes must not alter this baseline without testing.
    // RELEASE CHECKPOINT: 3D STUDIO V5 — stable web/mobile behavior baseline.
    // ================================================================

    const root = document.getElementById("customizer");
    const stage = document.getElementById("designer-3d-stage");
    const canvas = document.getElementById("designer-3d-canvas");
    if (!root || !stage || !canvas) return;

    let data = {};
    try {
        data = JSON.parse(document.getElementById("designer-data")?.textContent || "{}");
    } catch (error) {
        console.error("Invalid designer data", error);
        return;
    }

    const artworks = data.artworks || [];
    const variants = data.variants || [];
    const prices = data.prices || {};
    const areas = (data.views || []).flatMap(view => view.areas || []);
    const basePrice = Number(data.base_price || 0);
    const artworkById = id => artworks.find(item => Number(item.id) === Number(id));
    const areaById = (id, side = null) =>
        areas.find(item =>
            Number(item.id) === Number(id) &&
            (!side || item.side === side)
        ) || areas.find(item => Number(item.id) === Number(id));
    const esc = value => String(value ?? "").replace(/[&<>\\"']/g, char => ({
        "&":"&amp;","<":"&lt;",">":"&gt;","\\":"&quot;","'":"&#39;"
    }[char]));
    const money = value => Number(value || 0).toLocaleString("fa-IR");

    const TEXT_STYLE_PRESETS = {
        modern: { fontFamily: "Arial, Tahoma, sans-serif", fontWeight: 700, fontStyle: "normal" },
        classic: { fontFamily: "Georgia, 'Times New Roman', serif", fontWeight: 700, fontStyle: "normal" },
        impact: { fontFamily: "Impact, Haettenschweiler, sans-serif", fontWeight: 900, fontStyle: "normal" },
        mono: { fontFamily: "'Courier New', monospace", fontWeight: 700, fontStyle: "normal" },
        elegant: { fontFamily: "Georgia, 'Times New Roman', serif", fontWeight: 400, fontStyle: "italic" },
    };

    function normalizeTextStyle(style = {}) {
        const presetName = String(style.preset || "modern");
        const preset = TEXT_STYLE_PRESETS[presetName] || TEXT_STYLE_PRESETS.modern;
        return {
            preset: TEXT_STYLE_PRESETS[presetName] ? presetName : "modern",
            fontFamily: String(style.fontFamily || preset.fontFamily),
            fontWeight: Number(style.fontWeight || preset.fontWeight),
            fontStyle: style.fontStyle === "italic" ? "italic" : preset.fontStyle,
            fontSize: Math.max(60, Math.min(160, Number(style.fontSize ?? 100))),
            curve: Math.max(-80, Math.min(80, Number(style.curve ?? 0))),
            letterSpacing: Math.max(-2, Math.min(12, Number(style.letterSpacing ?? 0))),
        };
    }

    const textArtworkSvg = (text, color, rawStyle = {}) => {
        const safeText = esc(text);
        const safeColor = /^#[0-9a-f]{6}$/i.test(String(color || "")) ? color : "#ffffff";
        const style = normalizeTextStyle(rawStyle);
        const length = Math.max(1, String(text || "").length);
        const baseFontSize = length <= 12 ? 118 : length <= 20 ? 102 : length <= 34 ? 86 : 72;
        const fontSize = baseFontSize * (style.fontSize / 100);
        const curve = style.curve;
        const controlY = 225 - curve * 1.45;
        const pathId = `babaei-text-path-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

        const svg = curve
            ? `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420">
                <defs><path id="${pathId}" d="M 70 235 Q 450 ${controlY} 830 235"/></defs>
                <rect width="900" height="420" fill="none"/>
                <text fill="${safeColor}" font-family="${esc(style.fontFamily)}" font-size="${fontSize}px" font-weight="${style.fontWeight}" font-style="${style.fontStyle}" letter-spacing="${style.letterSpacing}px">
                    <textPath href="#${pathId}" startOffset="50%" text-anchor="middle">${safeText}</textPath>
                </text>
            </svg>`
            : `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="420" viewBox="0 0 900 420">
                <rect width="900" height="420" fill="none"/>
                <text x="450" y="225" text-anchor="middle" dominant-baseline="middle" font-family="${esc(style.fontFamily)}" font-size="${fontSize}px" font-weight="${style.fontWeight}" font-style="${style.fontStyle}" letter-spacing="${style.letterSpacing}px" fill="${safeColor}">${safeText}</text>
            </svg>`;

        return "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
    };


    let scene, camera, renderer, controls, garment;
    let garmentMeshes = [];
    let garmentMaterials = [];
    let garmentMaxSize = 3;
    let baseCameraDistance = 5.6;
    let garmentBaseScale = new THREE.Vector3(1, 1, 1);
    let currentVariant = null;
    let selectedId = null;
    let activeAreaId = areas[0]?.id || null;
    let nextId = 1;
    let drag = null;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const layers = new Map();
    const textures = new Map();
    const frontAxis = new THREE.Vector3(0, 0, 1);
    const garmentModels = {
        tshirt: {
            key: "tshirt",
            label: "تیشرت",
            url: stage.dataset.modelUrl,
            template: "babaei_tshirt_glb_v1",
            model: "Glb/whit_t_shirt.glb",
        },
    };
    let garmentType = "tshirt";
    let modelUrl = garmentModels.tshirt.url;
    const compactMedia = window.matchMedia("(max-width: 1023px)");
    let renderFrameId = 0;
    let shadowMapDirty = true;
    let resizePending = false;
    let garmentLocalBounds = null;
    let environmentReady = false;
    let pendingDragEvent = null;
    let dragFrameId = 0;

    let mobileDragHintTimer = 0;

    function showMobileDragHint() {
        if (!compactMedia.matches) return;
        const hint = document.getElementById("mobile-drag-hint");
        if (!hint) return;
        window.clearTimeout(mobileDragHintTimer);
        hint.hidden = false;
        mobileDragHintTimer = window.setTimeout(() => {
            hint.hidden = true;
        }, 3500);
    }

    function hideMobileDragHint() {
        const hint = document.getElementById("mobile-drag-hint");
        if (!hint) return;
        window.clearTimeout(mobileDragHintTimer);
        hint.hidden = true;
    }

    function status(text) {
        const el = document.getElementById("save-status");
        if (el) el.textContent = text || "";
    }

    function showModelPreview() {
        const preview = data.views?.[0]?.background;
        if (!preview) return;
        stage.style.backgroundImage =
            "radial-gradient(ellipse at 50% 40%, rgba(255,255,255,.07), transparent 34%)," +
            "radial-gradient(ellipse at 50% 82%, rgba(216,182,107,.045), transparent 38%)," +
            `url("${String(preview).replace(/"/g, "\\\"")}")`;
        stage.style.backgroundPosition = "center, center, center";
        stage.style.backgroundSize = "auto, auto, min(68vw, 420px) auto";
        stage.style.backgroundRepeat = "no-repeat, no-repeat, no-repeat";
    }

    function clearModelPreview() {
        stage.style.backgroundImage = "";
        stage.style.backgroundPosition = "";
        stage.style.backgroundSize = "";
        stage.style.backgroundRepeat = "";
    }

    function setLoading(text, visible = true) {
        const el = document.getElementById("designer-3d-loading");
        if (!el) return;
        el.textContent = text || "";
        el.classList.toggle("is-hidden", !visible);
    }

    function csrf() {
        const token = document.cookie.split(";").map(item => item.trim()).find(item => item.startsWith("csrftoken="));
        if (token) return decodeURIComponent(token.slice(10));

        return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    }

    function setupScene() {
        scene = new THREE.Scene();
        camera = new THREE.PerspectiveCamera(28, 1, 0.01, 100);

        renderer = new THREE.WebGLRenderer({
            canvas,
            antialias: true,
            alpha: true,
            powerPreference: "high-performance",
            // The cart preview is captured from this canvas after an explicit render.
            // Keeping the drawing buffer makes that one-time capture reliable.
            preserveDrawingBuffer: true,
        });
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.05;

        // Keep the existing look, but avoid rebuilding the shadow atlas on
        // every render. The shadow map only changes when the garment itself
        // changes; camera orbiting and label edits do not require a new map.
        const lowPowerDevice =
            compactMedia.matches ||
            Number(navigator.deviceMemory || 8) <= 4 ||
            Number(navigator.hardwareConcurrency || 8) <= 4;

        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        renderer.shadowMap.autoUpdate = false;

        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.055;
        controls.enablePan = false;
        controls.rotateSpeed = 0.62;
        controls.zoomSpeed = 0.72;
        controls.minPolarAngle = 0.82;
        controls.maxPolarAngle = 2.32;
        controls.target.set(0, 0, 0);
        controls.addEventListener("start", scheduleRenderLoop);
        controls.addEventListener("end", scheduleRenderLoop);

        scene.add(new THREE.HemisphereLight(0xffffff, 0x141414, 1.25));

        const key = new THREE.DirectionalLight(0xffffff, 3.2);
        key.position.set(3.5, 4.5, 5.5);
        key.castShadow = true;
        const shadowResolution = lowPowerDevice ? 512 : 1024;
        key.shadow.mapSize.set(shadowResolution, shadowResolution);
        scene.add(key);

        const fill = new THREE.DirectionalLight(0xdfe8ff, 1.25);
        fill.position.set(-4, 2.5, 2.5);
        scene.add(fill);

        const rim = new THREE.DirectionalLight(0xffdfb2, 1.15);
        rim.position.set(2.5, 3.2, -4.5);
        scene.add(rim);
    }

    function prepareMaterial(material) {
        if (!material) return;
        if (material.isMaterial) {
            material.needsUpdate = true;
            if ("roughness" in material && material.roughness == null) material.roughness = 0.82;
            if ("metalness" in material && material.metalness == null) material.metalness = 0;
            garmentMaterials.push(material);
        }
    }

    function applyResponsiveGarmentScale(rootObject = garment) {
        if (!rootObject) return;

        const isPhone = window.matchMedia("(max-width: 600px)").matches;
        rootObject.scale.set(
            garmentBaseScale.x,
            garmentBaseScale.y * (isPhone ? 1.12 : 1),
            garmentBaseScale.z
        );
    }

    function normalizeGarment(rootObject) {
        const box = new THREE.Box3().setFromObject(rootObject);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        const maxSize = Math.max(size.x, size.y, size.z) || 1;

        const targetHeight = 2.72;
        rootObject.scale.setScalar(targetHeight / maxSize);
        garmentBaseScale.copy(rootObject.scale);

        // Responsive proportions must be reversible because the user can
        // switch DevTools between desktop and phone without a page reload.
        applyResponsiveGarmentScale(rootObject);

        const scaledBox = new THREE.Box3().setFromObject(rootObject);
        const scaledCenter = scaledBox.getCenter(new THREE.Vector3());
        rootObject.position.sub(scaledCenter);
        rootObject.position.y += 0.02;

        const finalBox = new THREE.Box3().setFromObject(rootObject);
        const finalSize = finalBox.getSize(new THREE.Vector3());
        const finalMax = Math.max(finalSize.x, finalSize.y, finalSize.z);

        garmentMaxSize = finalMax;
        shadowMapDirty = true;
        controls.target.set(0, finalSize.y * 0.03, 0);
        controls.minDistance = Math.max(2.6, finalMax * 0.72);
        controls.maxDistance = Math.max(8.5, finalMax * 2.5);
        fitCamera(true);
    }

    function setupEnvironment() {
        if (environmentReady) return;

        const pmrem = new THREE.PMREMGenerator(renderer);
        const environment = new RoomEnvironment();
        scene.environment = pmrem.fromScene(environment, 0.03).texture;
        scene.environmentIntensity = 0.55;
        environment.dispose();
        pmrem.dispose();
        environmentReady = true;
    }

    async function loadGlb(loader, url) {
        const cacheName = "babaei-3d-models-v1";

        const parseArrayBuffer = arrayBuffer => new Promise((resolve, reject) => {
            const basePath = url.slice(0, url.lastIndexOf("/") + 1);
            loader.parse(arrayBuffer, basePath, resolve, reject);
        });

        if ("caches" in window) {
            try {
                const cache = await caches.open(cacheName);
                const cached = await cache.match(url);
                if (cached) {
                    return await parseArrayBuffer(await cached.arrayBuffer());
                }

                const response = await fetch(url, {
                    credentials: "same-origin",
                    cache: "force-cache",
                });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);

                void cache.put(url, response.clone()).catch(() => {});
                return await parseArrayBuffer(await response.arrayBuffer());
            } catch {
                // Cache Storage is best-effort; fall back to GLTFLoader below.
            }
        }

        return await new Promise((resolve, reject) => {
            loader.load(url, resolve, undefined, reject);
        });
    }

    function disposeObject3D(object) {
        if (!object) return;
        object.traverse(child => {
            if (!child.isMesh) return;
            child.geometry?.dispose();
            const materials = Array.isArray(child.material) ? child.material : [child.material];
            materials.forEach(material => {
                if (!material) return;
                material.map?.dispose();
                material.normalMap?.dispose();
                material.roughnessMap?.dispose();
                material.metalnessMap?.dispose();
                material.emissiveMap?.dispose();
                material.aoMap?.dispose();
                material.dispose?.();
            });
        });
    }

    async function loadGarment(nextUrl = modelUrl) {
        if (!nextUrl) throw new Error("مدل سه‌بعدی لباس تعریف نشده است.");

        setLoading("در حال بارگذاری مدل سه‌بعدی…", true);
        showModelPreview();
        const loader = new GLTFLoader();
        setupEnvironment();

        // Load the new GLB first. This way a failed switch never destroys the
        // currently visible garment.
        const gltf = await loadGlb(loader, nextUrl);

        const previousGarment = garment;
        if (previousGarment) {
            scene.remove(previousGarment);
            disposeObject3D(previousGarment);
        }

        garmentMeshes = [];
        garmentMaterials = [];
        garmentLocalBounds = null;

        garment = gltf.scene;
        garment.name = "BabaeiTshirtGLB";

        // Preserve the established mobile presentation angle. The full-stage
        // viewport fix must not reset the garment to a flat front view.
        garment.rotation.y = THREE.MathUtils.degToRad(-8);
        garment.traverse(object => {
            if (!object.isMesh) return;

            object.castShadow = true;
            object.receiveShadow = true;
            object.frustumCulled = true;
            garmentMeshes.push(object);

            if (Array.isArray(object.material)) object.material.forEach(prepareMaterial);
            else prepareMaterial(object.material);
        });

        if (!garmentMeshes.length) throw new Error("GLB فاقد Mesh قابل نمایش است.");

        // Keep the original PBR materials/textures from the supplied GLB.
        scene.add(garment);
        normalizeGarment(garment);
        shadowMapDirty = true;
        garmentLocalBounds = computeGarmentLocalBounds();
        clearModelPreview();
        setLoading("", false);
        render();
    }


    function fitCamera(initial = false) {
        if (!camera || !controls || !garment) return;

        const mobile = compactMedia.matches;
        const aspect = Math.max(0.35, camera.aspect || 1);

        // The mobile viewport is portrait, so the horizontal FOV is much
        // narrower than the vertical FOV. The camera must therefore be fitted
        // against BOTH the garment width and height. Fitting by height alone
        // crops the shoulders/sleeves on phones.
        //
        // A wider mobile FOV lets us keep the garment visually large while the
        // two-axis fit guarantees that the complete shirt remains inside the
        // canvas.
        // Portrait screens have very little horizontal field of view. A
        // slightly tighter mobile FOV keeps the garment prominent without
        // cropping the sleeves because the fit distance is still calculated
        // from both axes below.
        const targetFov = mobile ? 39 : 28;
        if (Math.abs(camera.fov - targetFov) > 0.01) {
            camera.fov = targetFov;
        }

        const box = new THREE.Box3().setFromObject(garment);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());

        const verticalFov = THREE.MathUtils.degToRad(camera.fov);
        const horizontalFov = 2 * Math.atan(
            Math.tan(verticalFov / 2) * aspect
        );

        const verticalDistance =
            size.y / (2 * Math.tan(verticalFov / 2));

        const horizontalDistance =
            size.x / (2 * Math.tan(horizontalFov / 2));

        // Phone reference frame:
        // - the garment center must sit at the real center of the phone viewport
        // - the shirt should occupy roughly 44% of the viewport width, matching
        //   the desired compact reference composition from the editor
        // - the same rule is used on first load and on desktop -> mobile resize,
        //   so the model cannot jump to a different frame after refresh.
        const isPhone = window.matchMedia("(max-width: 600px)").matches;

        // Desktop-only framing. Mobile keeps its existing branch below
        // unchanged so the currently-correct phone composition is preserved.
        const desktopFitDistance = Math.max(
            verticalDistance,
            horizontalDistance,
            size.z * 1.25
        );
        let distance = desktopFitDistance * 1.06;
        let targetY = center.y;
        let cameraY = center.y;

        if (isPhone) {
            // Only change the camera distance: CSS/canvas sizing stays untouched.
            // The 0.34 ratio controls the requested compact garment width, while
            // the final factor gives the additional size reduction the reference
            // screenshot needs.
            const targetWidthRatio = 0.34;
            const mobileWidthDistance =
                horizontalDistance / targetWidthRatio;

            distance = Math.max(
                verticalDistance,
                mobileWidthDistance,
                size.z * 1.25
            ) * 1.30;

            // Exact screen-center anchor. Do not compensate for the bottom
            // toolbar here; the toolbar is an overlay and the reference frame
            // intentionally keeps the garment centered in the full viewport.
            targetY = center.y;
            cameraY = center.y;
        }

        baseCameraDistance = distance;        camera.position.set(0, cameraY, distance);
        controls.target.set(center.x, targetY, center.z);

        camera.near = Math.max(0.01, distance / 100);
        camera.far = Math.max(100, distance * 20);
        camera.updateProjectionMatrix();

        if (initial) controls.update();
        render();
        updateCameraZoomLabel();
    }

    function updateCameraZoomLabel() {
        const label = document.getElementById("camera-zoom-label");
        if (!label || !camera || !controls) return;
        const current = camera.position.distanceTo(controls.target);
        const percent = Math.round((baseCameraDistance / Math.max(current, 0.01)) * 100);
        label.textContent = `${percent}%`;
    }

    function changeCameraZoom(factor) {
        if (!camera || !controls) return;
        const target = controls.target.clone();
        const direction = camera.position.clone().sub(target).normalize();
        const current = camera.position.distanceTo(target);
        const next = THREE.MathUtils.clamp(current * factor, controls.minDistance, controls.maxDistance);
        camera.position.copy(target).add(direction.multiplyScalar(next));
        controls.update();
        updateCameraZoomLabel();
        render();
    }

    function rotateGarment(step) {
        if (!garment) return;
        garment.rotation.y += THREE.MathUtils.degToRad(step);
        shadowMapDirty = true;
        render();
    }

    function resize() {
        if (!renderer || !camera) return;
        if (resizePending) return;

        resizePending = true;
        const apply = () => {
            resizePending = false;
            // Wait for the responsive CSS layout to settle before measuring
            // the stage. This prevents the desktop camera framing from
            // surviving the first desktop -> phone transition in DevTools.
            const stageRect = stage.getBoundingClientRect();
            const width = Math.max(1, Math.round(stageRect.width));
            const height = Math.max(1, Math.round(stageRect.height));

            const mobile = compactMedia.matches;
            const lowPowerDevice =
                mobile ||
                Number(navigator.deviceMemory || 8) <= 4 ||
                Number(navigator.hardwareConcurrency || 8) <= 4;
            const pixelRatioCap = lowPowerDevice
                ? 1.25
                : 1.75;

            if (garment) {
                applyResponsiveGarmentScale();
            }

            renderer.setPixelRatio(
                Math.min(window.devicePixelRatio || 1, pixelRatioCap)
            );
            renderer.setSize(width, height, false);

            camera.aspect = width / height;
            camera.updateProjectionMatrix();

            if (mobile) {
                canvas.style.position = "absolute";
                canvas.style.left = "0";
                canvas.style.right = "0";
                canvas.style.top = "0px";
                canvas.style.width = "100%";
                canvas.style.height = `${height}`;
            } else {
                canvas.style.position = "";
                canvas.style.left = "";
                canvas.style.right = "";
                canvas.style.top = "";
                canvas.style.width = "";
                canvas.style.height = "";
            }

            if (garment) fitCamera();
            else render();
        };

        apply();
        requestAnimationFrame(() => requestAnimationFrame(apply));
    }

    function render() {
        if (!renderer || !scene || !camera) return;

        if (renderer.shadowMap.enabled && shadowMapDirty) {
            renderer.shadowMap.needsUpdate = true;
            shadowMapDirty = false;
        }

        renderer.render(scene, camera);
    }

    function scheduleRenderLoop() {
        if (renderFrameId || !renderer || !scene || !camera) return;
        renderFrameId = requestAnimationFrame(() => {
            renderFrameId = 0;
            if (!controls) {
                render();
                return;
            }
            const changed = controls.update();
            render();
            if (changed) scheduleRenderLoop();
        });
    }

    function setColor(hex) {
        const base = new THREE.Color(hex || "#ffffff");
        garmentMaterials.forEach(material => {
            if (!material?.color) return;
            material.color.copy(base);
            material.needsUpdate = true;
        });
        render();
    }

    function loadTexture(url) {
        if (textures.has(url)) return textures.get(url);
        const promise = new THREE.TextureLoader().loadAsync(url).then(texture => {
            texture.colorSpace = THREE.SRGBColorSpace;
            const lowPowerDevice =
                compactMedia.matches ||
                Number(navigator.deviceMemory || 8) <= 4 ||
                Number(navigator.hardwareConcurrency || 8) <= 4;
            texture.anisotropy = Math.min(
                renderer.capabilities.getMaxAnisotropy(),
                lowPowerDevice ? 2 : 4
            );
            return texture;
        });
        textures.set(url, promise);
        return promise;
    }

    // Artwork files often contain transparent padding around the visible design.
    // That padding must not become part of the label's physical/collision area.
    const visibleTextureCache = new WeakMap();

    function cropTextureToVisiblePixels(texture) {
        if (!texture?.image) return { texture, owned: false };

        const cached = visibleTextureCache.get(texture);
        if (cached) return cached;

        try {
            const image = texture.image;
            const width = Number(image.width || image.naturalWidth || 0);
            const height = Number(image.height || image.naturalHeight || 0);
            if (!width || !height) return { texture, owned: false };

            const canvas = document.createElement("canvas");
            canvas.width = width;
            canvas.height = height;

            const context = canvas.getContext("2d", { willReadFrequently: true });
            if (!context) return { texture, owned: false };

            context.clearRect(0, 0, width, height);
            context.drawImage(image, 0, 0, width, height);

            const pixels = context.getImageData(0, 0, width, height).data;
            let minX = width;
            let minY = height;
            let maxX = -1;
            let maxY = -1;

            for (let y = 0; y < height; y += 1) {
                for (let x = 0; x < width; x += 1) {
                    const alpha = pixels[(y * width + x) * 4 + 3];
                    if (alpha <= 8) continue;

                    if (x < minX) minX = x;
                    if (x > maxX) maxX = x;
                    if (y < minY) minY = y;
                    if (y > maxY) maxY = y;
                }
            }

            // Completely transparent artwork: keep the original texture.
            if (maxX < minX || maxY < minY) {
                const result = { texture, owned: false };
                visibleTextureCache.set(texture, result);
                return result;
            }

            // Keep one pixel of breathing room so anti-aliased edges are not
            // accidentally clipped.
            const padding = 1;
            minX = Math.max(0, minX - padding);
            minY = Math.max(0, minY - padding);
            maxX = Math.min(width - 1, maxX + padding);
            maxY = Math.min(height - 1, maxY + padding);

            // Nothing to crop: the artwork already fills its image bounds.
            if (minX === 0 && minY === 0 && maxX === width - 1 && maxY === height - 1) {
                const result = {
                    texture,
                    owned: false,
                    visibleWidth: width,
                    visibleHeight: height,
                };
                visibleTextureCache.set(texture, result);
                return result;
            }

            const cropWidth = maxX - minX + 1;
            const cropHeight = maxY - minY + 1;
            const cropCanvas = document.createElement("canvas");
            cropCanvas.width = cropWidth;
            cropCanvas.height = cropHeight;

            const cropContext = cropCanvas.getContext("2d");
            if (!cropContext) return { texture, owned: false };

            cropContext.clearRect(0, 0, cropWidth, cropHeight);
            cropContext.drawImage(
                image,
                minX,
                minY,
                cropWidth,
                cropHeight,
                0,
                0,
                cropWidth,
                cropHeight
            );

            const croppedTexture = new THREE.CanvasTexture(cropCanvas);
            croppedTexture.colorSpace = THREE.SRGBColorSpace;
            croppedTexture.anisotropy = texture.anisotropy || 1;
            croppedTexture.needsUpdate = true;

            const result = {
                texture: croppedTexture,
                owned: true,
                visibleWidth: cropWidth,
                visibleHeight: cropHeight,
            };
            visibleTextureCache.set(texture, result);
            return result;
        } catch (error) {
            console.warn("Artwork alpha bounds could not be calculated", error);
            return { texture, owned: false };
        }
    }

    function pointerOf(event) {
        const rect = canvas.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }

    function garmentHits(event) {
        pointerOf(event);
        raycaster.setFromCamera(pointer, camera);
        return raycaster.intersectObjects(garmentMeshes, false);
    }

    function centerHit() {
        raycaster.setFromCamera(new THREE.Vector2(0, 0), camera);
        return raycaster.intersectObjects(garmentMeshes, false)[0] || null;
    }

    function computeGarmentLocalBounds() {
        if (!garment) return null;
        garment.updateMatrixWorld(true);

        const box = new THREE.Box3();
        const corners = Array.from({ length: 8 }, () => new THREE.Vector3());

        garmentMeshes.forEach(mesh => {
            if (!mesh.geometry) return;
            if (!mesh.geometry.boundingBox) mesh.geometry.computeBoundingBox();
            const source = mesh.geometry.boundingBox;
            if (!source) return;

            corners[0].set(source.min.x, source.min.y, source.min.z);
            corners[1].set(source.max.x, source.min.y, source.min.z);
            corners[2].set(source.min.x, source.max.y, source.min.z);
            corners[3].set(source.max.x, source.max.y, source.min.z);
            corners[4].set(source.min.x, source.min.y, source.max.z);
            corners[5].set(source.max.x, source.min.y, source.max.z);
            corners[6].set(source.min.x, source.max.y, source.max.z);
            corners[7].set(source.max.x, source.max.y, source.max.z);

            corners.forEach(corner => {
                const world = mesh.localToWorld(corner.clone());
                box.expandByPoint(garment.worldToLocal(world.clone()));
            });
        });

        return box.isEmpty() ? null : box;
    }

    function normalizedGarmentPoint(point) {
        if (!garment || !point) return null;
        if (!garmentLocalBounds) garmentLocalBounds = computeGarmentLocalBounds();
        if (!garmentLocalBounds) return null;

        const size = garmentLocalBounds.getSize(new THREE.Vector3());
        if (size.x <= 1e-6 || size.y <= 1e-6) return null;

        const local = garment.worldToLocal(point.clone());
        return {
            x: THREE.MathUtils.clamp(
                (local.x - garmentLocalBounds.min.x) / size.x,
                0,
                1
            ),
            y: THREE.MathUtils.clamp(
                1 - ((local.y - garmentLocalBounds.min.y) / size.y),
                0,
                1
            ),
        };
    }

    function pointInPolygon(point, polygon) {
        if (!point || !Array.isArray(polygon) || polygon.length < 3) return false;
        let inside = false;

        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const xi = Number(polygon[i]?.x);
            const yi = Number(polygon[i]?.y);
            const xj = Number(polygon[j]?.x);
            const yj = Number(polygon[j]?.y);
            const intersects = ((yi > point.y) !== (yj > point.y)) &&
                (point.x < ((xj - xi) * (point.y - yi)) / ((yj - yi) || Number.EPSILON) + xi);
            if (intersects) inside = !inside;
        }

        return inside;
    }

    function is3DPrintableArea(area) {
        if (!area) return false;
        const key = String(area.key || "").toLowerCase();
        const name = String(area.name || "").toLowerCase();
        return !/(sleeve|آستین|collar|یقه|inside|داخل)/i.test(key + " " + name);
    }

    function areaCenter(area) {
        const geometry = Array.isArray(area?.geometry) ? area.geometry : [];
        if (!geometry.length) return { x: 0.5, y: 0.5 };

        const total = geometry.reduce(
            (sum, point) => ({
                x: sum.x + Number(point.x || 0),
                y: sum.y + Number(point.y || 0),
            }),
            { x: 0, y: 0 }
        );

        return {
            x: total.x / geometry.length,
            y: total.y / geometry.length,
        };
    }

    function areaRelativePlacement(item) {
        const area = areaById(item?.layer?.area_id, layerSide(item));
        const normalized = normalizedGarmentPoint(item?.surfacePoint || item?.position);
        const geometry = Array.isArray(area?.geometry) ? area.geometry : [];
        if (!area || !normalized || geometry.length < 3) return null;

        const xs = geometry.map(point => Number(point.x));
        const ys = geometry.map(point => Number(point.y));
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const minY = Math.min(...ys);
        const maxY = Math.max(...ys);

        return {
            x: THREE.MathUtils.clamp(
                (normalized.x - minX) / Math.max(maxX - minX, Number.EPSILON),
                0,
                1
            ),
            y: THREE.MathUtils.clamp(
                (normalized.y - minY) / Math.max(maxY - minY, Number.EPSILON),
                0,
                1
            ),
        };
    }

    function garmentNdcBounds() {
        const worldBox = new THREE.Box3().setFromObject(garment);
        if (worldBox.isEmpty()) return null;

        const points = [];
        [worldBox.min.x, worldBox.max.x].forEach(x => {
            [worldBox.min.y, worldBox.max.y].forEach(y => {
                [worldBox.min.z, worldBox.max.z].forEach(z => {
                    points.push(new THREE.Vector3(x, y, z).project(camera));
                });
            });
        });

        return {
            minX: Math.min(...points.map(point => point.x)),
            maxX: Math.max(...points.map(point => point.x)),
            minY: Math.min(...points.map(point => point.y)),
            maxY: Math.max(...points.map(point => point.y)),
        };
    }

    function surfaceSide(normal) {
        const localNormal = normal.clone().normalize();

        // Front/back belongs to the shirt itself, not to the screen/world.
        // Convert the hit normal into garment-local space so rotating the shirt
        // never changes which physical side a label belongs to.
        if (garment) {
            const inverseRotation = garment.getWorldQuaternion(new THREE.Quaternion()).invert();
            localNormal.applyQuaternion(inverseRotation).normalize();
        }

        return localNormal.dot(frontAxis) >= 0 ? "front" : "back";
    }

    function cameraFacingGarmentSide() {
        if (!garment || !camera) return null;

        const localCamera = garment.worldToLocal(camera.position.clone());
        return localCamera.z >= 0 ? "front" : "back";
    }

    function areaForSurfaceSide(side, fallbackArea) {
        const explicitSides = areas.some(area => area.side === "front") && areas.some(area => area.side === "back");
        if (!explicitSides) return fallbackArea;
        return areas.find(area => is3DPrintableArea(area) && area.side === side) || fallbackArea;
    }

    function isValidPrintSurface(hit, area) {
        if (!hit || !area) return false;

        const normal = hitNormal(hit);
        const side = surfaceSide(normal);
        const explicitSides = areas.some(item => item.side === "front") && areas.some(item => item.side === "back");

        // When the backend defines separate front/back print areas, keep the
        // layer bound to the correct production area. If only one shared area
        // exists, both faces remain valid and the persisted layer.side tells us
        // which face the customer actually used.
        if (explicitSides && area.side && area.side !== side) return false;

        return Math.abs(normal.dot(frontAxis)) >= 0.35;
    }

    function printAreaGeometry(area) {
        const geometry = Array.isArray(area?.geometry) ? area.geometry : [];
        if (geometry.length < 3) return null;

        const xs = geometry.map(point => Number(point.x));
        const ys = geometry.map(point => Number(point.y));
        const minX = Math.min(...xs);
        const maxX = Math.max(...xs);
        const minY = Math.min(...ys);
        const maxY = Math.max(...ys);
        const width = Math.max(maxX - minX, Number.EPSILON);
        const height = Math.max(maxY - minY, Number.EPSILON);

        return {
            minX,
            minY,
            width,
            height,
            polygon: geometry.map(point => ({
                x: (Number(point.x) - minX) / width,
                y: (Number(point.y) - minY) / height,
            })),
        };
    }

    function pointOnSegment(point, start, end) {
        const cross = (end.y - start.y) * (point.x - start.x) -
            (end.x - start.x) * (point.y - start.y);
        if (Math.abs(cross) > 1e-7) return false;

        return (
            point.x >= Math.min(start.x, end.x) - 1e-7 &&
            point.x <= Math.max(start.x, end.x) + 1e-7 &&
            point.y >= Math.min(start.y, end.y) - 1e-7 &&
            point.y <= Math.max(start.y, end.y) + 1e-7
        );
    }

    function pointInPolygonInclusive(point, polygon) {
        if (!point || !Array.isArray(polygon) || polygon.length < 3) return false;

        for (let index = 0; index < polygon.length; index += 1) {
            const next = (index + 1) % polygon.length;
            if (pointOnSegment(point, polygon[index], polygon[next])) return true;
        }

        return pointInPolygon(point, polygon);
    }

    function properSegmentIntersection(firstStart, firstEnd, secondStart, secondEnd) {
        const cross = (a, b, c) =>
            (b.y - a.y) * (c.x - a.x) - (b.x - a.x) * (c.y - a.y);

        const firstA = cross(firstStart, firstEnd, secondStart);
        const firstB = cross(firstStart, firstEnd, secondEnd);
        const secondA = cross(secondStart, secondEnd, firstStart);
        const secondB = cross(secondStart, secondEnd, firstEnd);

        return (
            ((firstA > 1e-7 && firstB < -1e-7) || (firstA < -1e-7 && firstB > 1e-7)) &&
            ((secondA > 1e-7 && secondB < -1e-7) || (secondA < -1e-7 && secondB > 1e-7))
        );
    }

    function orientedRectCorners(placement) {
        const halfWidth = Number(placement.width || 0) / 2;
        const halfHeight = Number(placement.height || 0) / 2;
        const angle = THREE.MathUtils.degToRad(Number(placement.rotation || 0));
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);

        return [
            [-halfWidth, -halfHeight],
            [halfWidth, -halfHeight],
            [halfWidth, halfHeight],
            [-halfWidth, halfHeight],
        ].map(([localX, localY]) => ({
            x: Number(placement.x) + localX * cos - localY * sin,
            y: Number(placement.y) + localX * sin + localY * cos,
        }));
    }

    function placementFitsPrintArea(area, placement) {
        const geometry = printAreaGeometry(area);
        if (!geometry) return false;

        const corners = orientedRectCorners(placement);
        if (!corners.every(corner => pointInPolygonInclusive(corner, geometry.polygon))) {
            return false;
        }

        for (let index = 0; index < corners.length; index += 1) {
            const start = corners[index];
            const end = corners[(index + 1) % corners.length];

            for (let boundaryIndex = 0; boundaryIndex < geometry.polygon.length; boundaryIndex += 1) {
                const boundaryStart = geometry.polygon[boundaryIndex];
                const boundaryEnd = geometry.polygon[(boundaryIndex + 1) % geometry.polygon.length];
                if (properSegmentIntersection(start, end, boundaryStart, boundaryEnd)) {
                    return false;
                }
            }
        }

        return true;
    }

    function projectionsOverlap(firstPoints, secondPoints, axis) {
        const first = firstPoints.map(point => point.x * axis.x + point.y * axis.y);
        const second = secondPoints.map(point => point.x * axis.x + point.y * axis.y);
        return !(Math.max(...first) <= Math.min(...second) + 1e-7 ||
            Math.max(...second) <= Math.min(...first) + 1e-7);
    }

    function orientedPlacementsOverlap(first, second) {
        const firstPoints = orientedRectCorners(first);
        const secondPoints = orientedRectCorners(second);
        const axes = [];

        [firstPoints, secondPoints].forEach(points => {
            for (let index = 0; index < 2; index += 1) {
                const next = points[index + 1];
                const edge = {
                    x: next.x - points[index].x,
                    y: next.y - points[index].y,
                };
                const length = Math.hypot(edge.x, edge.y) || 1;
                axes.push({
                    x: -edge.y / length,
                    y: edge.x / length,
                });
            }
        });

        return axes.every(axis => projectionsOverlap(firstPoints, secondPoints, axis));
    }

    function placementFromPoint(area, point, width, height, rotation = 0) {
        const normalized = normalizedGarmentPoint(point);
        if (!normalized) return null;

        return {
            x: normalized.x,
            y: normalized.y,
            width: Number(width || 0.35),
            height: Number(height || 0.25),
            rotation: Number(rotation || 0),
        };
    }

    function placementForLayer(item, overrides = {}) {
        const normalized = normalizedGarmentPoint(item?.surfacePoint || item?.position);
        if (!normalized) return null;

        return {
            x: Number(overrides.x ?? normalized.x),
            y: Number(overrides.y ?? normalized.y),
            width: Number(overrides.width ?? item.layer.width ?? 0.35),
            height: Number(overrides.height ?? item.layer.height ?? 0.25),
            rotation: Number(overrides.rotation ?? item.layer.rotation ?? 0),
        };
    }

    function validateLayerPlacement(item, placement) {
        const area = areaById(item?.layer?.area_id, layerSide(item));
        if (!area || !placement) {
            return { ok: false, message: "ناحیه چاپ لباس معتبر نیست." };
        }

        // 3D body mode intentionally does not reserve a large invisible
        // rectangle around artwork. Every label can be placed next to another
        // label; the visible artwork itself is the only thing the user sees.
        return { ok: true };
    }

    function printAreaPointToNdc(area, x, y, bounds) {
        const geometry = printAreaGeometry(area);
        if (!geometry || !bounds) return null;

        const garmentX = geometry.minX + x * geometry.width;
        const garmentY = geometry.minY + y * geometry.height;
        const garmentWidth = Math.max(bounds.maxX - bounds.minX, 0.1);
        const garmentHeight = Math.max(bounds.maxY - bounds.minY, 0.1);

        return {
            x: bounds.minX + garmentX * garmentWidth,
            y: bounds.maxY - garmentY * garmentHeight,
        };
    }

    function placementHit(area, labelWidth = 0.35, labelHeight = 0.25, desiredSide = null) {
        if (!area || !camera || !garment) return null;

        const bounds = garmentNdcBounds();
        if (!bounds) return null;

        // Keep placement simple: the 3D shirt body is the canvas.
        // We only care about front/back and collisions with existing labels.
        const candidates = [
            [0.50, 0.42], [0.30, 0.42], [0.70, 0.42],
            [0.50, 0.30], [0.50, 0.56],
            [0.28, 0.30], [0.72, 0.30],
            [0.28, 0.56], [0.72, 0.56],
            [0.50, 0.68], [0.30, 0.68], [0.70, 0.68],
            [0.20, 0.42], [0.80, 0.42],
        ];

        // Pick a free-looking visual position, not a collision-free
        // rectangle. Labels are allowed to sit directly beside each other.
        const orderedCandidates = [...candidates].sort((a, b) => {
            if (!layers.size) return 0;

            const score = candidate => {
                let nearest = 1;
                for (const other of layers.values()) {
                    if (desiredSide && layerSide(other) !== desiredSide) continue;
                    const placement = placementForLayer(other);
                    if (!placement) continue;
                    nearest = Math.min(
                        nearest,
                        Math.hypot(candidate[0] - placement.x, candidate[1] - placement.y)
                    );
                }
                return nearest;
            };

            return score(b) - score(a);
        });

        for (const [x, y] of orderedCandidates) {
            const ndc = {
                x: bounds.minX + x * Math.max(bounds.maxX - bounds.minX, 0.1),
                y: bounds.maxY - y * Math.max(bounds.maxY - bounds.minY, 0.1),
            };

            raycaster.setFromCamera(new THREE.Vector2(
                THREE.MathUtils.clamp(ndc.x, -0.98, 0.98),
                THREE.MathUtils.clamp(ndc.y, -0.98, 0.98),
            ), camera);

            const hit = raycaster.intersectObjects(garmentMeshes, false)[0];
            if (!isValidPrintSurface(hit, area)) continue;

            const side = surfaceSide(hitNormal(hit));
            if (desiredSide && side !== desiredSide) continue;

            return hit;
        }

        return null;
    }

    function hitNormal(hit) {
        return (hit.face?.normal?.clone() || frontAxis.clone())
            .transformDirection(hit.object.matrixWorld)
            .normalize();
    }

    function orientation(normal, rotation) {
        const n = normal.clone().normalize();

        // Build a stable surface frame instead of using setFromUnitVectors().
        // The old approach has an unavoidable roll ambiguity when the normal is
        // on the back of the shirt, so tiny normal changes while dragging could
        // make the decal visibly spin. World-up gives the front and back a stable
        // "top" direction and we only rotate around the surface normal when the
        // user explicitly changes the label rotation.
        let up = new THREE.Vector3(0, 1, 0);
        up.addScaledVector(n, -up.dot(n));

        // Near a perfectly vertical normal, world-up has no usable projection.
        // Fall back to world-Z in that rare case.
        if (up.lengthSq() < 1e-6) {
            up.set(0, 0, 1);
            up.addScaledVector(n, -up.dot(n));
        }

        up.normalize();
        const right = new THREE.Vector3().crossVectors(up, n).normalize();

        const basis = new THREE.Matrix4().makeBasis(right, up, n);
        const frame = new THREE.Quaternion().setFromRotationMatrix(basis);
        const spin = new THREE.Quaternion().setFromAxisAngle(
            n,
            THREE.MathUtils.degToRad(Number(rotation) || 0)
        );

        return new THREE.Euler().setFromQuaternion(spin.multiply(frame));
    }

    function disposeLayer(item) {
        if (!item?.mesh) return;
        item.mesh.geometry?.dispose();
        // Textures are cached/shared between projections; dispose only the
        // per-decal material, otherwise a drag would invalidate the cached texture. 
        item.mesh.material?.dispose();
        item.mesh.parent?.remove(item.mesh);
        if (item.frame) {
            item.frame.geometry?.dispose();
            item.frame.material?.dispose();
            item.frame.parent?.remove(item.frame);
            item.frame = null;
        }
        if (item.handles) {
            item.handles.traverse(child => {
                child.geometry?.dispose();
                child.material?.dispose();
            });
            item.handles.parent?.remove(item.handles);
            item.handles = null;
        }
        item.mesh = null;
    }

    function garmentSurfaceHitAtPlacement(x, y, side) {
        if (!garment || !garmentLocalBounds || !garmentMeshes.length) return null;

        const size = garmentLocalBounds.getSize(new THREE.Vector3());
        if (size.x <= 1e-6 || size.y <= 1e-6 || size.z <= 1e-6) return null;

        const localX = garmentLocalBounds.min.x + THREE.MathUtils.clamp(Number(x ?? 0.5), 0, 1) * size.x;
        const localY = garmentLocalBounds.max.y - THREE.MathUtils.clamp(Number(y ?? 0.5), 0, 1) * size.y;
        const localMargin = Math.max(size.z * 0.75, 0.25);

        const localOrigin = new THREE.Vector3(
            localX,
            localY,
            side === "back"
                ? garmentLocalBounds.min.z - localMargin
                : garmentLocalBounds.max.z + localMargin
        );
        const localDirection = new THREE.Vector3(0, 0, side === "back" ? 1 : -1);

        const origin = garment.localToWorld(localOrigin.clone());
        const direction = localDirection
            .applyQuaternion(garment.getWorldQuaternion(new THREE.Quaternion()))
            .normalize();

        raycaster.set(origin, direction);
        const hits = raycaster.intersectObjects(garmentMeshes, false);
        return hits.find(hit => surfaceSide(hitNormal(hit)) === side) || null;
    }

    async function reprojectLayersAfterGarmentSwitch() {
        for (const item of layers.values()) {
            const side = String(item.layer.side || "front").toLowerCase() === "back"
                ? "back"
                : "front";
            const hit = garmentSurfaceHitAtPlacement(item.layer.x, item.layer.y, side);
            if (!hit) continue;

            item.target = hit.object;
            project(item, hit.point, hitNormal(hit));
        }

        selectedId = selectedId && layers.has(selectedId) ? selectedId : null;
        sync();
    }

    async function switchGarmentType(type) {
        const key = String(type || "").toLowerCase();
        const model = garmentModels[key];
        if (!model?.url) {
            status("مدل این لباس هنوز برای استودیو تنظیم نشده است.");
            return false;
        }
        if (key === garmentType && garment) return true;

        const previousType = garmentType;
        const previousUrl = modelUrl;
        garmentType = key;
        modelUrl = model.url;
        const title = document.getElementById("designer-product-title");
        if (title) title.textContent = model.label;

        try {
            await loadGarment(model.url);
            fitCamera(true);
            await reprojectLayersAfterGarmentSwitch();
            render();
            return true;
        } catch (error) {
            garmentType = previousType;
            modelUrl = previousUrl;
            const title = document.getElementById("designer-product-title");
            if (title) title.textContent = garmentModels[previousType]?.label || "طراحی تیشرت";
            console.error("garment type switch failed", error);
            status("تعویض مدل لباس انجام نشد.");
            return false;
        }
    }

    function project(item, point, normal) {
        if (!item?.artwork?.image || !garmentMeshes.length) return;

        // Keep the real cloth anchor separate from the tiny visual lift. The old
        // code re-used item.position when resizing, so the 0.018 offset was added
        // again and again until the decal floated away and disappeared.
        const surfacePoint = point.clone();
        const surfaceNormal = normal.clone().normalize();
        const revision = (item.projectRevision || 0) + 1;
        item.projectRevision = revision;

        loadTexture(item.artwork.image).then(sourceTexture => {
            if (!layers.has(item.id) || item.projectRevision !== revision) return;

            const cropped = cropTextureToVisiblePixels(sourceTexture);
            const texture = cropped.texture;
            item.visibleTexture = texture;
            item.visibleArtworkWidth = cropped.visibleWidth || texture.image?.width || 0;
            item.visibleArtworkHeight = cropped.visibleHeight || texture.image?.height || 0;

            item.normal = surfaceNormal.clone();
            item.surfacePoint = surfacePoint.clone();
            item.surfaceNormal = surfaceNormal.clone();
            item.position = surfacePoint.clone().addScaledVector(surfaceNormal, 0.008);

            // Use the cropped artwork aspect ratio. The transparent padding
            // around the original file is no longer part of the label.
            const aspect = Math.max(
                0.15,
                (cropped.visibleWidth || texture.image?.width || 1) /
                    Math.max(1, cropped.visibleHeight || texture.image?.height || 1)
            );
            item.renderAspect = aspect;

            const width = Math.max(0.08, Math.min(1.05, 0.86 * Number(item.layer.width || 0.35)));
            const size = new THREE.Vector3(
                width,
                width / aspect,
                Math.max(0.24, width * 0.9)
            );
            item.size = size;

            const target = item.target?.isMesh ? item.target : garmentMeshes[0];
            const geometry = new DecalGeometry(
                target,
                item.position,
                orientation(item.normal, item.layer.rotation),
                size
            );

            // DecalGeometry can legitimately produce an empty geometry when the
            // pointer is on a thin/angled part of the garment (especially sleeves).
            // Never remove the currently visible label until the replacement has
            // actually intersected the garment.
            if (!geometry.attributes.position?.count) {
                geometry.dispose();
                return;
            }

            const material = new THREE.MeshPhysicalMaterial({
                map: texture,
                // Artwork files already contain their intended colors. White
                // keeps those colors intact instead of multiplying them by a
                // saved label tint.
                color: new THREE.Color("#ffffff"),
                transparent: true,
                opacity: Math.max(0.2, Math.min(1, Number(item.layer.opacity ?? 1))),
                alphaTest: 0.02,
                roughness: 0.62,
                metalness: 0,
                clearcoat: 0.02,
                // A small emissive contribution restores the vivid colors seen
                // in the label library without making the artwork look flat.
                emissive: new THREE.Color("#ffffff"),
                emissiveMap: texture,
                emissiveIntensity: 0.16,
                depthTest: true,
                depthWrite: false,
                polygonOffset: true,
                polygonOffsetFactor: -5,
                polygonOffsetUnits: -2,
                side: THREE.DoubleSide,
            });

            // DecalGeometry is generated in world space. Convert it into the target
            // mesh's local space and parent it to that mesh so it stays physically
            // attached when the garment rotates.
            geometry.applyMatrix4(target.matrixWorld.clone().invert());

            const mesh = new THREE.Mesh(geometry, material);
            mesh.renderOrder = 30 + Number(item.layer.z_index || 0);
            mesh.userData.customizerLayerId = item.id;
            target.add(mesh);

            // Professional selection frame: a subtle gold outline that follows the
            // same surface/rotation as the decal and remains attached to the garment.
            const frameGeometry = new THREE.EdgesGeometry(
                new THREE.PlaneGeometry(size.x, size.y)
            );
            const frameMaterial = new THREE.LineBasicMaterial({
                color: 0xd8b66b,
                transparent: true,
                opacity: 0.92,
                depthTest: false,
                depthWrite: false,
            });
            const frame = new THREE.LineSegments(frameGeometry, frameMaterial);
            const targetWorldPosition = item.position.clone();
            target.worldToLocal(targetWorldPosition);
            frame.position.copy(targetWorldPosition);
            const worldQuaternion = new THREE.Quaternion().setFromEuler(
                orientation(item.normal, item.layer.rotation)
            );
            const targetWorldQuaternion = target.getWorldQuaternion(new THREE.Quaternion());
            frame.quaternion.copy(targetWorldQuaternion.clone().invert().multiply(worldQuaternion));
            frame.userData.customizerLayerId = item.id;
            frame.renderOrder = 80;
            target.add(frame);

            // Four compact handles make the selected artwork feel like a real
            // mobile design editor without adding another DOM overlay.
            const handleGroup = new THREE.Group();
            handleGroup.position.copy(targetWorldPosition);
            handleGroup.quaternion.copy(targetWorldQuaternion.clone().invert().multiply(worldQuaternion));
            handleGroup.userData.customizerLayerId = item.id;
            handleGroup.renderOrder = 81;

            const handleSize = Math.max(0.026, Math.min(size.x, size.y) * 0.045);
            const handleGeometry = new THREE.SphereGeometry(handleSize, 12, 8);
            const handleMaterial = new THREE.MeshBasicMaterial({
                color: 0xf4f0e7,
                transparent: true,
                opacity: 0.98,
                depthTest: false,
                depthWrite: false,
            });

            [
                [-size.x / 2, -size.y / 2],
                [ size.x / 2, -size.y / 2],
                [ size.x / 2,  size.y / 2],
                [-size.x / 2,  size.y / 2],
            ].forEach(([x, y]) => {
                const handle = new THREE.Mesh(handleGeometry.clone(), handleMaterial.clone());
                handle.position.set(x, y, 0);
                handle.renderOrder = 82;
                handle.userData.customizerLayerId = item.id;
                handleGroup.add(handle);
            });
            target.add(handleGroup);

            const previousMesh = item.mesh;
            const previousFrame = item.frame;
            const previousHandles = item.handles;

            item.mesh = mesh;
            item.frame = frame;
            item.handles = handleGroup;

            if (previousMesh) {
                previousMesh.geometry?.dispose();
                previousMesh.material?.dispose();
                previousMesh.parent?.remove(previousMesh);
            }
            if (previousFrame) {
                previousFrame.geometry?.dispose();
                previousFrame.material?.dispose();
                previousFrame.parent?.remove(previousFrame);
            }
            if (previousHandles) {
                previousHandles.traverse(child => {
                    child.geometry?.dispose();
                    child.material?.dispose();
                });
                previousHandles.parent?.remove(previousHandles);
            }

            scheduleRenderLoop();
        }).catch(() => status("تصویر لیبل برای پیش‌نمایش بارگذاری نشد."));
    }

    function addText(textValue, rawStyle = {}, rawColor = "#ffffff") {
        const text = String(textValue || "").trim().slice(0, 60);
        if (!text) return false;

        const style = normalizeTextStyle(rawStyle);
        const color = /^#[0-9a-f]{6}$/i.test(String(rawColor || ""))
            ? String(rawColor)
            : "#ffffff";

        const artwork = {
            id: `text-${Date.now()}`,
            name: text,
            code: "TEXT",
            image: textArtworkSvg(text, color, style),
            base_price: 0,
            is_text: true,
            text_style: style,
        };

        const added = addLayer(artwork);
        if (!added) return false;

        const item = layers.get(selectedId);
        if (!item?.artwork?.is_text) return false;

        item.layer.text = text;
        item.layer.text_style = style;
        item.layer.color = color;
        item.artwork.text_style = style;
        project(item, item.surfacePoint, item.surfaceNormal);
        sync();
        return true;
    }

    document.addEventListener("babaei:add-text", event => {
        addText(
            event.detail?.text,
            event.detail?.style || {},
            event.detail?.color || "#ffffff"
        );
    });

    document.addEventListener("babaei:update-text", event => {
        const item = layers.get(selectedId);
        const text = String(event.detail?.text ?? "").trim().slice(0, 60);
        if (!item?.artwork?.is_text || !text) return;

        const style = normalizeTextStyle(
            event.detail?.style || item.layer.text_style || item.artwork.text_style || {}
        );

        item.layer.text = text;
        item.layer.text_style = style;
        item.artwork.name = text;
        item.artwork.text_style = style;
        item.artwork.image = textArtworkSvg(
            text,
            item.layer.color || "#ffffff",
            style
        );

        project(
            item,
            item.surfacePoint || item.position,
            item.surfaceNormal || item.normal
        );
        sync();
    });

    document.addEventListener("babaei:update-text-style", event => {
        const item = layers.get(selectedId);
        if (!item?.artwork?.is_text) return;

        const style = normalizeTextStyle({
            ...(item.layer.text_style || item.artwork.text_style || {}),
            ...(event.detail?.style || {}),
        });

        item.layer.text_style = style;
        item.artwork.text_style = style;
        item.artwork.image = textArtworkSvg(
            item.layer.text || item.artwork.name || "TEXT",
            item.layer.color || "#ffffff",
            style
        );

        project(
            item,
            item.surfacePoint || item.position,
            item.surfaceNormal || item.normal
        );
        sync();
    });

    function addLayer(artworkOrId) {
        const artwork = typeof artworkOrId === "object" && artworkOrId ? artworkOrId : artworkById(artworkOrId);
        let area = areaById(activeAreaId);

        if (!artwork || !area || !is3DPrintableArea(area)) {
            status("این ناحیه برای چاپ سه‌بعدی لیبل قابل استفاده نیست.");
            return;
        }

        // Resolve the print area from the surface currently facing the user
        // before placing the label. This is important for back-side artwork:
        // the active UI area can still be the front area while the camera is
        // looking at the back of the shirt.
        // The side for a newly added label comes from the side of the shirt
        // currently facing the camera. This is independent from the last
        // selected label/area, so adding a label while viewing the back always
        // creates a back label.
        const cameraSide = cameraFacingGarmentSide();
        if (cameraSide) {
            area = areaForSurfaceSide(cameraSide, area);
        }

        const desiredSide = cameraSide || area?.side || null;
        let hit = placementHit(area, 0.35, 0.25, desiredSide);

        // If the center ray did not give us a usable surface, keep the selected
        // area and try its collision-aware candidates. Never bypass the
        // collision check for a second/third label.
        if (!hit && layers.size === 0) {
            raycaster.setFromCamera(new THREE.Vector2(0, 0), camera);
            const fallbackHit = raycaster.intersectObjects(garmentMeshes, false)[0];
            if (isValidPrintSurface(fallbackHit, area)) hit = fallbackHit;
        }

        if (!hit) {
            status("فضای کافی برای قرار دادن لیبل روی این سمت لباس وجود ندارد.");
            return false;
        }

        if (!hit) {
            status("لیبل فقط روی بدنه مجاز لباس قرار می‌گیرد.");
            return false;
        }

        const side = surfaceSide(hitNormal(hit));
        area = areaForSurfaceSide(side, area);
        const layer = {
            id: nextId++,
            artwork_id: artwork.id,
            area_id: area.id,
            x: 0.5,
            y: 0.5,
            width: 0.35,
            height: 0.25,
            rotation: 0,
            color: "#ffffff",
            opacity: 1,
            z_index: layers.size,
            text: artwork.is_text ? String(artwork.name || "TEXT") : null,
            text_style: artwork.is_text ? normalizeTextStyle(artwork.text_style || {}) : null,
            side,
        };

        const item = {
            id: layer.id,
            layer,
            artwork,
            target: hit.object,
            position: hit.point.clone(),
            normal: hitNormal(hit),
            surfacePoint: hit.point.clone(),
            surfaceNormal: hitNormal(hit),
            projectRevision: 0,
            mesh: null,
            frame: null,
            size: null,
        };

        layers.set(item.id, item);
        selectedId = item.id;
        project(item, item.surfacePoint, item.surfaceNormal);
        sync();
        showMobileDragHint();
        document.dispatchEvent(new CustomEvent("babaei:label-added"));
        return true;
    }

    function moveSelected(event) {
        const item = layers.get(selectedId);
        if (!item) return;

        const area = areaById(item.layer.area_id, layerSide(item));
        pointerOf(event);
        raycaster.setFromCamera(pointer, camera);
        const hit = raycaster.intersectObjects(garmentMeshes, false)[0];
        if (!isValidPrintSurface(hit, area)) {
            status("لیبل فقط روی بدنه جلو یا پشت تیشرت قابل جابه‌جایی است.");
            return;
        }

        // A label belongs to the side where it was created. When the user
        // rotates the shirt to the opposite side, dragging must not re-anchor
        // that front label onto the back surface (or vice versa).
        const hitSide = surfaceSide(hitNormal(hit));
        if (hitSide !== layerSide(item)) {
            return;
        }

        const placement = placementFromPoint(
            area,
            hit.point,
            item.layer.width,
            item.layer.height,
            item.layer.rotation,
        );
        const validation = validateLayerPlacement(item, placement);
        if (!validation.ok) {
            status(validation.message);
            return;
        }

        item.target = hit.object;
        project(item, hit.point, hitNormal(hit));
    }

    function moveSelectedBy(dx, dy) {
        const item = layers.get(selectedId);
        if (!item?.target || !item.surfacePoint || !item.surfaceNormal) return;

        const area = areaById(item.layer.area_id, layerSide(item));
        const normal = item.surfaceNormal.clone().normalize();
        const up = new THREE.Vector3(0, 1, 0).projectOnPlane(normal);
        if (up.lengthSq() < 0.0001) up.set(0, 0, 1);
        up.normalize();

        const right = new THREE.Vector3().crossVectors(up, normal).normalize();
        const step = Math.max(0.012, (item.size?.x || 0.35) * 0.08);
        const candidate = item.surfacePoint.clone()
            .addScaledVector(right, dx * step)
            .addScaledVector(up, dy * step);

        const origin = candidate.clone().addScaledVector(normal, 0.45);
        const direction = normal.clone().multiplyScalar(-1);
        const probe = new THREE.Raycaster(origin, direction, 0, 0.9);
        const hit = probe.intersectObject(item.target, false)[0];
        if (!isValidPrintSurface(hit, area)) {
            status("لیبل فقط روی بدنه جلو یا پشت تیشرت قابل جابه‌جایی است.");
            return;
        }

        const placement = placementFromPoint(
            area,
            hit.point,
            item.layer.width,
            item.layer.height,
            item.layer.rotation,
        );
        const validation = validateLayerPlacement(item, placement);
        if (!validation.ok) {
            status(validation.message);
            return;
        }

        item.target = hit.object;
        project(item, hit.point, hitNormal(hit));
    }

    function renderAreas() {
        const host = document.getElementById("area-list");
        if (!host) return;

        const printableAreas = areas.filter(is3DPrintableArea);
        if (!activeAreaId || !printableAreas.some(area => Number(area.id) === Number(activeAreaId))) {
            activeAreaId = printableAreas[0]?.id || null;
        }

        if (!printableAreas.length) {
            host.innerHTML = "<div class=\"area-option area-option--empty\"><span>ناحیه چاپ سه‌بعدی تعریف نشده است.</span></div>";
            return;
        }

        host.innerHTML = printableAreas.map(area => {
            return `<button type="button" class="area-option ${Number(area.id) === Number(activeAreaId) ? "is-active" : ""}" data-area-id="${area.id}">
                <span>${esc(area.name)}</span>
            </button>`;
        }).join("");

        host.querySelectorAll(".area-option").forEach(button => {
            button.addEventListener("click", () => {
                activeAreaId = Number(button.dataset.areaId);
                sync();
            });
        });
    }

    function sync() {
        const selected = layers.get(selectedId);
        document.dispatchEvent(new CustomEvent("babaei:selection-changed", {
            detail: {
                selected: Boolean(selected),
                id: selectedId,
                isText: Boolean(selected?.artwork?.is_text),
                text: selected?.artwork?.is_text
                    ? String(selected.layer.text || selected.artwork.name || "")
                    : "",
                textStyle: selected?.artwork?.is_text
                    ? normalizeTextStyle(selected.layer.text_style || selected.artwork.text_style || {})
                    : null,
                color: selected?.layer?.color || null,
            }
        }));
        const card = document.getElementById("selected-card");
        const controls = document.getElementById("selected-controls");
        const chosen = document.getElementById("premium-selected-artwork");
        const scaleInput = document.getElementById("label-scale");
        const rotationInput = document.getElementById("label-rotation");

        if (card) {
            card.innerHTML = selected
                ? `<div class="selected-card__title">${esc(selected.artwork.name || "لیبل")}</div><span class="selected-card__meta">${esc(areaById(selected.layer.area_id, layerSide(selected))?.name || "ناحیه چاپ")} · ${Math.round(selected.layer.width * 100)}%</span>`
                : `<span class="selected-card__empty">یک لیبل را انتخاب کنید.</span>`;
        }

        if (controls) controls.hidden = !selected;
        layers.forEach(item => {
            const visible = item.id === selectedId;
            if (item.frame) item.frame.visible = visible;
            if (item.handles) item.handles.visible = visible;
        });
        if (scaleInput) {
            scaleInput.disabled = !selected;
            scaleInput.value = selected ? String(Math.round(selected.layer.width * 100)) : "35";
        }
        if (rotationInput) {
            rotationInput.disabled = !selected;
            rotationInput.value = selected ? String(Math.round(selected.layer.rotation)) : "0";
        }

        if (chosen) {
            chosen.innerHTML = selected
                ? `<div class="premium-selected-artwork__name">لیبل انتخاب‌شده: <strong>${esc(selected.artwork.name || "لیبل")}</strong></div><div class="premium-selected-artwork__code">${esc(selected.artwork.code || "LBL")}</div><div class="premium-selected-artwork__hint">برای جابه‌جایی، مستقیم روی تیشرت بکش.</div>`
                : "";
        }

        let total = basePrice;
        const lines = [`<div class="price-line"><span>تیشرت</span><strong>${money(total)} تومان</strong></div>`];

        layers.forEach(item => {
            const key = `${item.layer.artwork_id}:${item.layer.area_id}`;
            const price = Object.prototype.hasOwnProperty.call(prices, key)
                ? Number(prices[key])
                : Number(item.artwork.base_price || 0);
            total += price;
            lines.push(`<div class="price-line"><span>${esc(item.artwork.name || "لیبل")}</span><strong>+ ${money(price)}</strong></div>`);
        });

        const breakdown = document.getElementById("price-breakdown");
        if (breakdown) breakdown.innerHTML = lines.join("");

        const totalEl = document.getElementById("designer-total");
        if (totalEl) totalEl.textContent = money(total);

        renderAreas();
    }

    function layerSide(item) {
        if (!item?.normal || !garment) return "front";
        const localNormal = item.normal.clone().applyQuaternion(garment.quaternion.clone().invert()).normalize();
        return localNormal.z >= 0 ? "front" : "back";
    }

    function imageFromSource(src) {
        return new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = reject;
            image.crossOrigin = "anonymous";
            image.src = src;
        });
    }

    function canvasBlob(canvas, type = "image/webp", quality = 0.88) {
        return new Promise(resolve => canvas.toBlob(resolve, type, quality));
    }

    async function build2DPreview(side) {
        const view = (data.views || []).find(item => {
            const value = `${item.key || ""} ${item.name || ""}`.toLowerCase();
            return side === "front"
                ? /(front|جلو|رو)/i.test(value)
                : /(back|پشت)/i.test(value);
        }) || (side === "front" ? data.views?.[0] : null);
        if (!view?.background) return null;

        const background = await imageFromSource(view.background);
        const canvas = document.createElement("canvas");
        const scale = Math.min(1, 1800 / Math.max(background.naturalWidth || background.width, background.naturalHeight || background.height));
        canvas.width = Math.max(1, Math.round((background.naturalWidth || background.width) * scale));
        canvas.height = Math.max(1, Math.round((background.naturalHeight || background.height) * scale));
        const ctx = canvas.getContext("2d");
        ctx.drawImage(background, 0, 0, canvas.width, canvas.height);

        const viewAreas = view.areas || [];
        const areaByIdLocal = id => viewAreas.find(area => Number(area.id) === Number(id));
        const sideLayers = Array.from(layers.values()).filter(item => layerSide(item) === side);

        for (const item of sideLayers) {
            const area = areaByIdLocal(item.layer.area_id);
            const geometry = area?.geometry || [];
            if (geometry.length < 3) continue;
            const xs = geometry.map(point => Number(point.x));
            const ys = geometry.map(point => Number(point.y));
            const minX = Math.min(...xs), maxX = Math.max(...xs);
            const minY = Math.min(...ys), maxY = Math.max(...ys);
            const areaWidth = Math.max(maxX - minX, 0.0001);
            const areaHeight = Math.max(maxY - minY, 0.0001);
            const placement = areaRelativePlacement(item) || { x: item.layer.x, y: item.layer.y };
            const x = (minX + placement.x * areaWidth) * canvas.width;
            const y = (minY + placement.y * areaHeight) * canvas.height;
            const width = item.layer.width * areaWidth * canvas.width;
            const height = item.layer.height * areaHeight * canvas.height;

            ctx.save();
            ctx.translate(x, y);
            ctx.rotate(Number(item.layer.rotation || 0) * Math.PI / 180);
            if (item.artwork?.is_text) {
                const style = normalizeTextStyle(item.layer.text_style || item.artwork.text_style || {});
                ctx.fillStyle = item.layer.color || "#ffffff";
                ctx.font = `${style.fontStyle} ${style.fontWeight} ${Math.max(12, height * 0.48)}px ${style.fontFamily}`;
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(String(item.layer.text || item.artwork.name || ""), 0, 0, Math.max(width, 20));
            } else if (item.artwork?.image) {
                try {
                    const artworkImage = await imageFromSource(item.artwork.image);
                    ctx.globalAlpha = Number(item.layer.opacity ?? 1);
                    ctx.drawImage(artworkImage, -width / 2, -height / 2, width, height);
                } catch (error) {
                    console.warn("2D artwork preview failed", error);
                }
            }
            ctx.restore();
        }
        return canvasBlob(canvas);
    }

    function build3DPreviewAtRotation(rotationY, viewSide = "front") {
        return new Promise(resolve => {
            if (!renderer || !scene || !camera || !canvas || !garment) {
                resolve(null);
                return;
            }

            let settled = false;
            const finish = blob => {
                if (settled) return;
                settled = true;
                resolve(blob || null);
            };

            const previousRotation = garment.rotation.y;
            const previousCameraPosition = camera.position.clone();
            const previousCameraQuaternion = camera.quaternion.clone();
            const previousCameraTarget = controls?.target?.clone();
            const previousZoom = camera.zoom;

            const restoreEditorView = () => {
                garment.rotation.y = previousRotation;
                garment.updateMatrixWorld(true);
                camera.position.copy(previousCameraPosition);
                camera.quaternion.copy(previousCameraQuaternion);
                camera.zoom = previousZoom;
                camera.updateProjectionMatrix();

                if (previousCameraTarget && controls?.target) {
                    controls.target.copy(previousCameraTarget);
                    controls.update();
                }

                render();
            };

            // Cart previews are product shots, not screenshots of the current
            // editor angle. Even if the customer rotated the shirt sideways,
            // always generate a straight-on front and a straight-on back.
            const capture = () => {
                try {
                    garment.rotation.y = rotationY;
                    garment.updateMatrixWorld(true);

                    // Fit the camera to the actual garment bounds. This removes
                    // the editor's arbitrary orbit angle and keeps the whole
                    // shirt visible without cutting sleeves or the hem.
                    const bounds = new THREE.Box3().setFromObject(garment);
                    const center = bounds.getCenter(new THREE.Vector3());
                    const size = bounds.getSize(new THREE.Vector3());
                    const radius = Math.max(size.x, size.y, size.z) * 0.5;
                    const fovRadians = THREE.MathUtils.degToRad(camera.fov || 35);
                    const distance = Math.max(
                        1.2,
                        (radius / Math.max(0.2, Math.tan(fovRadians * 0.5))) * 1.28
                    );

                    // The shirt itself keeps one canonical physical orientation.
                    // To photograph the back, move the camera to the back side;
                    // do NOT rotate the garment, otherwise we would photograph
                    // the front again from the opposite world direction.
                    const cameraZ = viewSide === "back" ? -distance : distance;
                    camera.position.set(center.x, center.y, center.z + cameraZ);
                    camera.lookAt(center);
                    camera.updateProjectionMatrix();

                    if (controls?.target) {
                        controls.target.copy(center);
                    }

                    render();

                    requestAnimationFrame(() => {
                        try {
                            render();
                            canvas.toBlob(
                                blob => {
                                    restoreEditorView();
                                    finish(blob);
                                },
                                "image/webp",
                                0.9
                            );
                        } catch (error) {
                            restoreEditorView();
                            console.warn("3D cart preview failed", error);
                            finish(null);
                        }
                    });
                } catch (error) {
                    restoreEditorView();
                    console.warn("3D cart preview failed", error);
                    finish(null);
                }
            };

            const timeout = window.setTimeout(() => {
                restoreEditorView();
                finish(null);
            }, 1800);

            // rotationY < 0 is the canonical front shot, +PI is the canonical
            // back shot. The exact sign is intentionally handled by the caller.
            capture();
        });
    }
    function build3DPreview() {
        return build3DPreviewAtRotation(garment?.rotation?.y ?? 0);
    }

    function saveLayers() {
        return Array.from(layers.values()).map(item => {
            const bodyPlacement = placementForLayer(item);
            const side = layerSide(item);
            return {
                ...item.layer,
                type: item.artwork?.is_text ? "text" : "artwork",
                side,
                x: bodyPlacement?.x ?? item.layer.x,
                y: bodyPlacement?.y ?? item.layer.y,
                color: item.layer.color || "#ffffff",
                opacity: Number(item.layer.opacity ?? 1),
                text: item.artwork?.is_text ? String(item.layer.text || item.artwork.name || "") : null,
                text_style: item.artwork?.is_text ? normalizeTextStyle(item.layer.text_style || item.artwork.text_style || {}) : null,
                three_d: {
                    position: item.position?.toArray().map(value => Number(value.toFixed(6))) || null,
                    normal: item.normal?.toArray().map(value => Number(value.toFixed(6))) || null,
                    mesh: item.target?.name || null,
                    size: item.size?.toArray().map(value => Number(value.toFixed(6))) || null,
                    side,
                    mode: "glb_surface_decal",
                    template: garmentModels[garmentType]?.template || "babaei_tshirt_glb_v1",
                    model: garmentModels[garmentType]?.model || "Glb/whit_t_shirt.glb",
                    coordinate_space: "garment_body",
                    label: {
                        id: item.artwork?.id ?? null,
                        code: item.artwork?.code || null,
                        name: item.artwork?.name || "",
                        image: item.artwork?.image || null,
                        background_removed: item.artwork?.background_removed !== false,
                    },
                },
            };
        });
    }

    function bind() {
        document.getElementById("customizer-back-button")?.addEventListener("click", () => {
            if (window.history.length > 1) {
                window.history.back();
                return;
            }

            const fallbackUrl = root.dataset.productUrl;
            if (fallbackUrl) window.location.assign(fallbackUrl);
        });

        canvas.addEventListener("pointerdown", event => {
            if (compactMedia.matches) hideMobileDragHint();
            const intersections = garmentHits(event);
            const decal = raycaster.intersectObjects(
                Array.from(layers.values()).map(item => item.mesh).filter(Boolean),
                true
            ).find(hit => hit.object?.userData?.customizerLayerId != null);

            if (decal) {
                selectedId = Number(decal.object.userData.customizerLayerId);
                drag = { pointerId: event.pointerId };
                controls.enabled = false;
                canvas.setPointerCapture(event.pointerId);
                sync();
                return;
            }

            if (event.button === 1 || event.altKey) return;

            // A selected label must only move after the user starts dragging the label itself.
            // Clicking another point on the garment must never teleport the selected label.
            return;
        });

        canvas.addEventListener("pointermove", event => {
            if (drag?.pointerId !== event.pointerId) return;
            pendingDragEvent = event;
            if (dragFrameId) return;

            dragFrameId = requestAnimationFrame(() => {
                dragFrameId = 0;
                const latestEvent = pendingDragEvent;
                pendingDragEvent = null;
                if (drag?.pointerId === latestEvent?.pointerId) {
                    moveSelected(latestEvent);
                }
            });
        });

        ["pointerup", "pointercancel"].forEach(type => {
            canvas.addEventListener(type, event => {
                if (drag?.pointerId !== event.pointerId) return;
                // Apply the last coalesced pointer position before ending the drag.
                if (pendingDragEvent?.pointerId === event.pointerId) {
                    moveSelected(pendingDragEvent);
                }
                pendingDragEvent = null;
                if (dragFrameId) {
                    cancelAnimationFrame(dragFrameId);
                    dragFrameId = 0;
                }
                drag = null;
                controls.enabled = true;
                canvas.releasePointerCapture?.(event.pointerId);
                sync();
            });
        });

        document.querySelectorAll("[data-action]").forEach(button => {
            button.addEventListener("click", () => {
                const item = layers.get(selectedId);
                if (!item) return;

                const action = button.dataset.action;

                if (action === "move-left") {
                    moveSelectedBy(-1, 0);
                } else if (action === "move-right") {
                    moveSelectedBy(1, 0);
                } else if (action === "move-up") {
                    moveSelectedBy(0, 1);
                } else if (action === "move-down") {
                    moveSelectedBy(0, -1);
                } else if (action === "scale-up" || action === "scale-down") {
                    const factor = action === "scale-up" ? 1.06 : 0.94;
                    const previousWidth = item.layer.width;
                    const previousHeight = item.layer.height;
                    item.layer.width = Math.min(0.98, Math.max(0.06, item.layer.width * factor));
                    item.layer.height = Math.min(0.98, Math.max(0.04, item.layer.height * factor));

                    const validation = validateLayerPlacement(item, placementForLayer(item));
                    if (!validation.ok) {
                        item.layer.width = previousWidth;
                        item.layer.height = previousHeight;
                        status(validation.message);
                    } else {
                        project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
                    }
                } else if (action === "rotate-left" || action === "rotate-right") {
                    const previousRotation = item.layer.rotation;
                    item.layer.rotation = Math.max(
                        -180,
                        Math.min(180, item.layer.rotation + (action === "rotate-left" ? -5 : 5))
                    );

                    const validation = validateLayerPlacement(item, placementForLayer(item));
                    if (!validation.ok) {
                        item.layer.rotation = previousRotation;
                        status(validation.message);
                    } else {
                        project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
                    }
                } else if (action === "center-label") {
                    const hit = placementHit(
                        areaById(item.layer.area_id, layerSide(item)),
                        item.layer.width,
                        item.layer.height,
                        layerSide(item),
                    );
                    if (hit) {
                        item.target = hit.object;
                        project(item, hit.point, hitNormal(hit));
                    } else {
                        status("فضای آزاد مناسبی برای مرکز کردن این لیبل پیدا نشد.");
                    }
                } else if (action === "delete") {
                    disposeLayer(item);
                    layers.delete(selectedId);
                    selectedId = null;
                }

                sync();
                render();
            });
        });

        document.querySelectorAll("[data-mode]").forEach(button => {
            button.addEventListener("click", () => {
                const is3d = button.dataset.mode === "3d";
                document.getElementById("designer-2d-stage")?.classList.toggle("is-hidden", is3d);
                stage.classList.toggle("is-hidden", !is3d);
                document.querySelectorAll("[data-mode]").forEach(item => item.classList.toggle("is-active", item === button));
                if (is3d) resize();
            });
        });

        document.getElementById("variant-select")?.addEventListener("change", event => {
            const variant = variants.find(item => String(item.id) === String(event.target.value)) || null;
            currentVariant = variant;
            setColor(variant?.hex || "#ffffff");
            sync();
        });

        document.getElementById("designer-3d-rotation")?.addEventListener("input", event => {
            if (!garment) return;
            garment.rotation.y = THREE.MathUtils.degToRad(Number(event.target.value));
            render();
        });

        document.getElementById("label-scale")?.addEventListener("input", event => {
            const item = layers.get(selectedId);
            if (!item) return;

            const previousWidth = item.layer.width;
            const previousHeight = item.layer.height;
            const value = THREE.MathUtils.clamp(Number(event.target.value) / 100, 0.06, 0.98);
            item.layer.width = value;
            item.layer.height = Math.max(0.04, Math.min(0.78, value * 0.72));

            const validation = validateLayerPlacement(item, placementForLayer(item));
            if (!validation.ok) {
                item.layer.width = previousWidth;
                item.layer.height = previousHeight;
                event.target.value = String(Math.round(previousWidth * 100));
                status(validation.message);
                sync();
                return;
            }

            project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
            sync();
        });

        document.getElementById("label-rotation")?.addEventListener("input", event => {
            const item = layers.get(selectedId);
            if (!item) return;

            const previousRotation = item.layer.rotation;
            item.layer.rotation = THREE.MathUtils.clamp(Number(event.target.value), -180, 180);

            const validation = validateLayerPlacement(item, placementForLayer(item));
            if (!validation.ok) {
                item.layer.rotation = previousRotation;
                event.target.value = String(previousRotation);
                status(validation.message);
                sync();
                return;
            }

            project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
            sync();
        });

        document.querySelectorAll("[data-camera-action]").forEach(button => {
            button.addEventListener("click", () => {
                const action = button.dataset.cameraAction;
                if (action === "rotate-left") rotateGarment(-15);
                if (action === "rotate-right") rotateGarment(15);
                if (action === "zoom-in") changeCameraZoom(0.88);
                if (action === "zoom-out") changeCameraZoom(1.14);
                if (action === "fit") fitCamera();
                if (action === "reset") {
                    if (garment) garment.rotation.y = 0;
                    controls?.reset();
                    fitCamera();
                }
            });
        });

        document.getElementById("designer-3d-reset")?.addEventListener("click", () => {
            if (garment) garment.rotation.y = 0;
            controls?.reset();
            fitCamera();
            render();
        });

        document.addEventListener("babaei:set-layer-color", event => {
            const item = layers.get(selectedId);
            const color = String(event.detail?.color || "").trim();
            if (!item || !/^#[0-9a-f]{6}$/i.test(color)) return;

            item.layer.color = color;
            if (item.artwork?.is_text || item.artwork?.code === "TEXT") {
                item.artwork.image = textArtworkSvg(
                    item.layer.text || item.artwork.name || "TEXT",
                    color,
                    item.layer.text_style || item.artwork.text_style || {}
                );
                project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
            } else if (item.mesh?.material?.color) {
                item.mesh.material.color.set(color);
                item.mesh.material.needsUpdate = true;
            }
            render();
        });

        document.addEventListener("babaei:set-layer-opacity", event => {
            const item = layers.get(selectedId);
            if (!item) return;

            const opacity = Math.max(0.2, Math.min(1, Number(event.detail?.opacity ?? 1)));
            item.layer.opacity = opacity;
            if (item.mesh?.material) {
                item.mesh.material.opacity = opacity;
                item.mesh.material.needsUpdate = true;
            }
            render();
        });

        document.addEventListener("babaei:deselect-label", () => {
            selectedId = null;
            sync();
            render();
        });

        const cartConfirm = document.getElementById("designer-cart-confirm");
        const cartConfirmSubmit = document.getElementById("designer-cart-confirm-submit");
        const closeCartConfirm = () => {
            if (cartConfirm) cartConfirm.hidden = true;
            document.body.classList.remove("designer-cart-confirm-open");
        };
        cartConfirm?.querySelectorAll("[data-cart-confirm-cancel]").forEach(control => {
            control.addEventListener("click", event => {
                event.preventDefault();
                closeCartConfirm();
            });
        });
        cartConfirmSubmit?.addEventListener("click", event => {
            event.preventDefault();
            const button = document.getElementById("add-to-cart-design");
            if (!button) return;
            button.dataset.cartConfirmed = "1";
            closeCartConfirm();
            button.click();
        });

        document.getElementById("add-to-cart-design")?.addEventListener("click", async event => {
            event.preventDefault();
            event.stopImmediatePropagation();
            const button = event.currentTarget;

            if (button.dataset.cartConfirmed !== "1") {
                if (cartConfirm) {
                    cartConfirm.hidden = false;
                    document.body.classList.add("designer-cart-confirm-open");
                }
                return;
            }

            button.dataset.cartConfirmed = "";

            // Always resolve the variant from the visible selector at submit time.
            // This prevents a visual-only color change from leaving the cart on an older variant.
            const selectedVariant = variants.find(
                variant => String(variant.id) === String(document.getElementById("variant-select")?.value)
            ) || currentVariant;

            const selectedVendorOption = document.getElementById("designer-vendor-listing")?.selectedOptions[0];
            const sellerStock = selectedVendorOption?.value
                ? Number(selectedVendorOption.dataset.stock || 0)
                : Number(selectedVariant?.stock || 0);
            if (!selectedVariant?.id || sellerStock <= 0) {
                status("لطفاً یک رنگ و سایز موجود و یک فروشنده دارای موجودی را انتخاب کنید.");
                return;
            }
            currentVariant = selectedVariant;

            button.disabled = true;
            status("در حال آماده‌سازی طراحی…");
            try {
                // The cart preview must represent the actual 3D design.
                // Product/background images can belong to a completely different
                // product (for example a cap), so they are never used as the
                // custom-design thumbnail.
                // Never use the customer's current orbit/rotation for
                // cart thumbnails. These are canonical product views.
                const frontPreview = await build3DPreviewAtRotation(0, "front");
                const backPreview = await build3DPreviewAtRotation(0, "back");
                const payload = {
                    variant_id: selectedVariant.id,
                    version: 2,
                    preview_mode: "3d_glb_tshirt",
                    coordinate_space: "garment_body",
                    garment_spec: data.garment_spec || null,
                    shirt_color: selectedVariant.color || selectedVariant.hex || "",
                    garment_type: garmentType,
                    garment_model: garmentModels[garmentType]?.model || "",
                    layers: saveLayers(),
                };
                const form = new FormData();
                form.append("payload", JSON.stringify(payload));
                if (frontPreview) form.append("preview_front", frontPreview, "front.webp");
                if (backPreview) form.append("preview_back", backPreview, "back.webp");
                const response = await fetch(root.dataset.cartUrl, {
                    method: "POST",
                    headers: { "X-CSRFToken": csrf() },
                    credentials: "same-origin",
                    body: form,
                });

                const responseText = await response.text();
                let result = {};
                try {
                    result = responseText ? JSON.parse(responseText) : {};
                } catch {
                    result = {};
                }

                if (!response.ok || !result.ok) {
                    const serverMessage =
                        result.message ||
                        result.error ||
                        (response.status === 403
                            ? "درخواست توسط امنیت سایت رد شد. صفحه را یک‌بار تازه‌سازی کنید."
                            : ("افزودن به سبد انجام نشد (خطای " + response.status + ")."));
                    throw new Error(serverMessage);
                }
                status(`طراحی ${String(result.design_code || "")} به سبد اضافه شد.`);
                window.location.href = root.dataset.cartPageUrl || "/cart/";
            } catch (error) {
                console.error("custom design cart failed", error);
                status(error.message || "افزودن طراحی به سبد انجام نشد.");
            } finally {
                button.disabled = false;
            }
        });  }

    async function init() {
        setupScene();
        currentVariant = variants.find(variant => Number(variant.stock) > 0) || variants[0] || null;

        const variantSelect = document.getElementById("variant-select");
        if (variantSelect && currentVariant) variantSelect.value = currentVariant.id;

        renderAreas();
        bind();
        resize();

        try {
            await loadGarment();
            setColor(currentVariant?.hex || "#ffffff");
            sync();
        } catch (error) {
            console.error("GLB customizer model failed to load", error);
            setLoading("بارگذاری مدل سه‌بعدی انجام نشد.", true);
            status("مدل سه‌بعدی تیشرت بارگذاری نشد. مسیر GLB یا دسترسی فایل را بررسی کنید.");
        }
    }

    init();

    const resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(stage);
    window.addEventListener("orientationchange", resize, { passive: true });
    compactMedia.addEventListener?.("change", resize);
    window.matchMedia("(max-width: 600px)").addEventListener?.("change", resize);

    window.addEventListener("pagehide", () => {
        if (renderFrameId) cancelAnimationFrame(renderFrameId);
        resizeObserver.disconnect();
        controls?.dispose();
        renderer?.dispose();
    }, { once: true });

    window.BabaeiCustomizer3D = {
        getPayload: saveLayers,
        isReady: () => Boolean(garment && garmentMeshes.length),
        setMode: mode => document.querySelector(`[data-mode="${mode}"]`)?.click(),
        setShirtColor: setColor,
        setVariant: variantId => {
            const variant = variants.find(item => String(item.id) === String(variantId));
            if (!variant) return false;
            currentVariant = variant;
            const select = document.getElementById("variant-select");
            if (select) select.value = String(variant.id);
            setColor(variant.hex || "#ffffff");
            sync();
            return true;
        },
        getVariant: () => currentVariant ? { ...currentVariant } : null,
        addArtwork: addLayer,
        addText,
        setGarmentType: switchGarmentType,
        getGarmentType: () => garmentType,
    };
})();