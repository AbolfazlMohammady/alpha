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
    let selectedPreviewDrag = null;
    let selectedPreviewFrameId = 0;
    let pendingSelectedPreviewEvent = null;
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const layers = new Map();
    const textures = new Map();
    const selectedPreviewImages = new Map();
    const frontAxis = new THREE.Vector3(0, 0, 1);
    const garmentModelOptions = Array.from(
        document.querySelectorAll("[data-garment-type][data-model-url]")
    );
    const patternManifestUrl = document.getElementById("garment-model-registry")?.dataset.patternManifestUrl || "";
    let patternManifestPromise = null;

    async function loadPatternManifest() {
        if (!patternManifestUrl) return null;
        if (!patternManifestPromise) {
            const manifestAbsoluteUrl = new URL(patternManifestUrl, window.location.href).href;
            patternManifestPromise = fetch(manifestAbsoluteUrl, {
                credentials: "same-origin",
                cache: "no-cache",
            }).then(async response => {
                if (!response.ok) throw new Error("Pattern manifest HTTP " + response.status);
                return response.json();
            }).catch(error => {
                console.warn("2D garment pattern manifest is not available yet.", error);
                return null;
            });
        }
        return patternManifestPromise;
    }

    function viewMatchesSide(view, side) {
        const label = String(view?.key || "") + " " + String(view?.name || "");
        return side === "front"
            ? /(front|جلو|روبه|رو)/i.test(label)
            : /(back|پشت)/i.test(label);
    }

    async function resolve2DPatternView(side, { forceGenerated = false } = {}) {
        const databaseView = (data.views || []).find(view => viewMatchesSide(view, side)) || null;
        if (!forceGenerated && databaseView?.background) return databaseView;

        const manifest = await loadPatternManifest();
        if (!manifest?.generated) return forceGenerated ? null : databaseView;
        const pattern = manifest.models?.[garmentType];
        const patternSide = pattern?.views?.[side];
        if (!pattern?.svg || !patternSide?.geometry?.length) {
            return forceGenerated ? null : databaseView;
        }

        const manifestAbsoluteUrl = new URL(patternManifestUrl, window.location.href).href;
        const background = new URL(pattern.svg, manifestAbsoluteUrl).href;
        const sideAreas = areas.filter(area => area.side === side);
        const mappedAreas = sideAreas.map(area => ({
            ...area,
            // Mapped coordinates now belong to the generated SVG page, not a photo canvas.
            geometry: patternSide.geometry,
        }));

        return {
            ...(databaseView || {}),
            id: databaseView?.id ?? (side === "front" ? -1 : -2),
            key: side,
            name: side === "front" ? "الگوی جلو" : "الگوی پشت",
            background,
            width: pattern.page?.width || 1600,
            height: pattern.page?.height || 1600,
            areas: mappedAreas,
            patternName: pattern.name,
        };
    }
    const garmentModels = {
        tshirt: {
            key: "tshirt",
            label: "تیشرت",
            url: stage.dataset.modelUrl,
            template: "babaei_tshirt_glb_v1",
            model: "Glb/whit_t_shirt.glb",
        },
    };

    for (const option of garmentModelOptions) {
        const key = String(option.dataset.garmentType || "").trim().toLowerCase();
        const url = String(option.dataset.modelUrl || "").trim();
        if (!key || !url) continue;

        garmentModels[key] = {
            key,
            label: option.dataset.garmentLabel || option.textContent.trim(),
            url,
            template: option.dataset.garmentTemplate || `babaei_${key}_glb_v1`,
            model: option.dataset.modelPath || url,
            targetSize: Number(option.dataset.garmentTargetSize) || 2.72,
        };
    }

    let garmentType = "tshirt";
    let modelUrl = garmentModels.tshirt.url;
    const studioViewStorageKey = `babaei-customizer:view:${root.dataset.productSlug || "default"}`;

    function readPreferredStudioView() {
        try {
            const saved = window.localStorage.getItem(studioViewStorageKey);
            return ["2d", "split", "3d"].includes(saved) ? saved : "split";
        } catch (error) {
            return "split";
        }
    }

    let preferredStudioView = readPreferredStudioView();
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
        // Re-apply the selected Scene tab backdrop after the temporary model preview clears.
        applySceneBackdrop();
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

        // Garments keep the established 2.72 display size. The mug has a
        // wider, more compact silhouette, so it uses a smaller target size to
        // match the visual footprint of the other product models.
        const targetSize = garmentModels[garmentType]?.targetSize || 2.72;
        rootObject.scale.setScalar(targetSize / maxSize);
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
        const previousTarget = controls.target.clone();
        const previousOffset = camera.position.clone().sub(previousTarget);
        const previousDistance = Math.max(previousOffset.length(), 0.01);
        const previousBaseDistance = Math.max(baseCameraDistance || previousDistance, 0.01);
        const previousZoomRatio = previousDistance / previousBaseDistance;
        const previousDirection = previousOffset.normalize();

        const targetFov = mobile ? 39 : 28;
        if (Math.abs(camera.fov - targetFov) > 0.01) {
            camera.fov = targetFov;
        }

        garment.updateWorldMatrix(true, true);
        const box = new THREE.Box3().setFromObject(garment);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());

        const verticalFov = THREE.MathUtils.degToRad(camera.fov);
        const horizontalFov = 2 * Math.atan(
            Math.tan(verticalFov / 2) * aspect
        );
        const verticalDistance = size.y / (2 * Math.tan(verticalFov / 2));
        const horizontalDistance = size.x / (2 * Math.tan(horizontalFov / 2));

        const isPhone = window.matchMedia("(max-width: 600px)").matches;
        const desktopFitDistance = Math.max(
            verticalDistance,
            horizontalDistance,
            size.z * 1.25
        );

        let fitDistance = desktopFitDistance * 1.08;
        if (isPhone) {
            fitDistance = Math.max(
                verticalDistance,
                horizontalDistance / 0.34,
                size.z * 1.25
            ) * 1.30;
        }

        // On first load / garment switch, use a near-frontal view with a
        // small elevation so chest artwork is readable without orbiting.
        // On responsive resize, preserve the user's current orbit and zoom.
        const defaultDirection = new THREE.Vector3(0, 0.095, 1).normalize();
        const direction = initial || previousOffset.lengthSq() < 1e-6
            ? defaultDirection
            : previousDirection;

        const zoomRatio = initial
            ? 1
            : THREE.MathUtils.clamp(previousZoomRatio, 0.68, 2.25);
        const distance = THREE.MathUtils.clamp(
            fitDistance * zoomRatio,
            Math.max(controls.minDistance || 0.1, fitDistance * 0.55),
            Math.min(controls.maxDistance || fitDistance * 3, fitDistance * 2.4)
        );

        baseCameraDistance = fitDistance;
        controls.target.copy(center);
        camera.position.copy(center).add(direction.multiplyScalar(distance));
        camera.near = Math.max(0.01, distance / 120);
        camera.far = Math.max(100, distance * 24);
        camera.updateProjectionMatrix();
        camera.lookAt(center);

        // OrbitControls keeps an internal spherical state. Updating it on every
        // fit (not only the first one) prevents stale camera orientation after
        // a panel resize, garment switch, or split/3D view transition.
        controls.update();
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
        const loader = new THREE.TextureLoader();
        loader.setCrossOrigin("anonymous");
        const promise = loader.loadAsync(new URL(url, window.location.href).href).then(texture => {
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
        }).catch(error => {
            // A failed request must not poison the URL cache forever.
            textures.delete(url);
            throw error;
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

    function garmentLocalNormal(worldNormal) {
        const localNormal = worldNormal.clone().normalize();
        if (!garment) return localNormal;

        garment.updateWorldMatrix(true, false);
        const garmentNormalMatrix = new THREE.Matrix3().getNormalMatrix(garment.matrixWorld);
        garmentNormalMatrix.invert();
        return localNormal.applyMatrix3(garmentNormalMatrix).normalize();
    }

    function surfaceSide(normal) {
        return garmentLocalNormal(normal).dot(frontAxis) >= 0 ? "front" : "back";
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

        const localNormal = garmentLocalNormal(normal);
        return Math.abs(localNormal.dot(frontAxis)) >= 0.35;
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
        if (!hit?.object) return frontAxis.clone();

        hit.object.updateWorldMatrix(true, false);
        const normalMatrix = new THREE.Matrix3().getNormalMatrix(hit.object.matrixWorld);
        return (hit.face?.normal?.clone() || frontAxis.clone())
            .applyMatrix3(normalMatrix)
            .normalize();
    }

    function orientation(normal, rotation) {
        garment?.updateWorldMatrix(true, false);
        const n = normal.clone().normalize();

        // Build a stable surface frame instead of using setFromUnitVectors().
        // The old approach has an unavoidable roll ambiguity when the normal is
        // on the back of the shirt, so tiny normal changes while dragging could
        // make the decal visibly spin. World-up gives the front and back a stable
        // "top" direction and we only rotate around the surface normal when the
        // user explicitly changes the label rotation.
        // Use the garment's own vertical axis rather than global world-up.
        // Imported hoodie / long-sleeve GLBs can have slightly different root
        // orientations, so world-up can make artwork appear skewed on them.
        let up = garment
            ? new THREE.Vector3(0, 1, 0).transformDirection(garment.matrixWorld)
            : new THREE.Vector3(0, 1, 0);
        up.addScaledVector(n, -up.dot(n));

        if (up.lengthSq() < 1e-6) {
            up = garment
                ? new THREE.Vector3(1, 0, 0).transformDirection(garment.matrixWorld)
                : new THREE.Vector3(0, 0, 1);
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
        if (!item) return;
        if (item.mesh) {
            item.mesh.geometry?.dispose();
            item.mesh.parent?.remove(item.mesh);
        }
        // Release the per-layer material once the layer itself is removed.
        item.decalMaterial?.dispose();
        item.decalMaterial = null;
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

    function updateGarmentPicker(activeKey, busy = false) {
        garmentModelOptions.forEach(option => {
            const active = option.dataset.garmentType === activeKey;
            option.classList.toggle("is-active", active);
            option.setAttribute("aria-pressed", String(active));
            option.disabled = busy;
        });
    }

    async function switchGarmentType(type) {
        const key = String(type || "").toLowerCase();
        const model = garmentModels[key];
        if (!model?.url) {
            status("مدل این محصول برای استودیو سه‌بعدی تنظیم نشده است.");
            return false;
        }
        if (key === garmentType && garment) {
            updateGarmentPicker(key, false);
            return true;
        }

        const previousType = garmentType;
        const previousUrl = modelUrl;
        updateGarmentPicker(previousType, true);
        garmentType = key;
        modelUrl = model.url;

        try {
            await loadGarment(model.url);
            fitCamera(true);
            await reprojectLayersAfterGarmentSwitch();
            render();
            // Mugs temporarily force 3D; garments restore the selected view.
            setStudioView(preferredStudioView);

            const title = document.getElementById("designer-product-title");
            if (title) title.textContent = `طراحی ${model.label}`;
            return true;
        } catch (error) {
            garmentType = previousType;
            modelUrl = previousUrl;
            const title = document.getElementById("designer-product-title");
            if (title) title.textContent = `طراحی ${garmentModels[previousType]?.label || "تیشرت"}`;
            console.error("garment type switch failed", error);
            status("تعویض مدل محصول انجام نشد.");
            return false;
        } finally {
            updateGarmentPicker(garmentType, false);
        }
    }

    garmentModelOptions.forEach(option => {
        option.addEventListener("click", () => {
            void switchGarmentType(option.dataset.garmentType);
        });
    });
    updateGarmentPicker("tshirt", true);


    function buildProjectedLayer(item, point, normal, options = {}) {
        if (!item?.artwork?.image || !garmentMeshes.length) return false;

        const surfacePoint = point.clone();
        const surfaceNormal = normal.clone().normalize();
        const target = item.target?.isMesh ? item.target : garmentMeshes[0];
        const cropped = item.visibleArtwork || null;
        const texture = item.visibleTexture || null;
        if (!texture || !cropped) return false;

        texture.repeat.set(item.layer.flip_x ? -1 : 1, item.layer.flip_y ? -1 : 1);
        texture.offset.set(item.layer.flip_x ? 1 : 0, item.layer.flip_y ? 1 : 0);
        texture.needsUpdate = true;

        const aspect = Math.max(
            0.15,
            (cropped.visibleWidth || texture.image?.width || 1) /
                Math.max(1, cropped.visibleHeight || texture.image?.height || 1)
        );
        const width = Math.max(0.08, Math.min(1.05, 0.86 * Number(item.layer.width || 0.35)));
        const size = new THREE.Vector3(
            width,
            width / aspect,
            THREE.MathUtils.clamp(width * 0.16, 0.045, 0.085)
        );
        const position = surfacePoint.clone().addScaledVector(surfaceNormal, 0.008);
        const geometry = new DecalGeometry(
            target,
            position,
            orientation(surfaceNormal, item.layer.rotation),
            size
        );

        if (!geometry.attributes.position?.count) {
            geometry.dispose();
            return false;
        }

        geometry.applyMatrix4(target.matrixWorld.clone().invert());

        const previousMesh = item.mesh;
        const previousFrame = item.frame;
        const previousHandles = item.handles;

        let material = item.decalMaterial;
        if (!material) {
            material = new THREE.MeshPhysicalMaterial({
                map: texture,
                color: new THREE.Color("#ffffff"),
                transparent: true,
                opacity: Math.max(0.2, Math.min(1, Number(item.layer.opacity ?? 1))),
                alphaTest: 0.02,
                roughness: 0.62,
                metalness: 0,
                clearcoat: 0.02,
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
            item.decalMaterial = material;
        } else {
            material.map = texture;
            material.emissiveMap = texture;
            material.opacity = Math.max(0.2, Math.min(1, Number(item.layer.opacity ?? 1)));
            material.needsUpdate = true;
        }

        const mesh = new THREE.Mesh(geometry, material);
        mesh.renderOrder = 30 + (Number(item.layer.z_index) || 0);
        mesh.visible = item.layer.visible !== false;
        mesh.userData.customizerLayerId = item.id;
        target.add(mesh);

        const frameGeometry = new THREE.EdgesGeometry(new THREE.PlaneGeometry(size.x, size.y));
        const frameMaterial = new THREE.LineBasicMaterial({
            color: 0xd8b66b,
            transparent: true,
            opacity: 0.92,
            depthTest: false,
            depthWrite: false,
        });
        const frame = new THREE.LineSegments(frameGeometry, frameMaterial);
        const targetWorldPosition = position.clone();
        target.worldToLocal(targetWorldPosition);
        frame.position.copy(targetWorldPosition);
        const worldQuaternion = new THREE.Quaternion().setFromEuler(
            orientation(surfaceNormal, item.layer.rotation)
        );
        const targetWorldQuaternion = target.getWorldQuaternion(new THREE.Quaternion());
        frame.quaternion.copy(targetWorldQuaternion.clone().invert().multiply(worldQuaternion));
        frame.userData.customizerLayerId = item.id;
        frame.renderOrder = 80;
        frame.visible = item.id === selectedId && item.layer.visible !== false;
        target.add(frame);

        const handleGroup = new THREE.Group();
        handleGroup.position.copy(targetWorldPosition);
        handleGroup.quaternion.copy(targetWorldQuaternion.clone().invert().multiply(worldQuaternion));
        handleGroup.userData.customizerLayerId = item.id;
        handleGroup.renderOrder = 81;
        handleGroup.visible = item.id === selectedId && item.layer.visible !== false && !item.layer.locked;

        const isTouchEditor = compactMedia.matches || (navigator.maxTouchPoints || 0) > 0;
        const handleSize = Math.max(
            isTouchEditor ? 0.038 : 0.026,
            Math.min(size.x, size.y) * (isTouchEditor ? 0.065 : 0.05)
        );
        const handleGeometry = new THREE.SphereGeometry(handleSize, 12, 10);
        const handleMaterial = new THREE.MeshBasicMaterial({
            color: 0xf8f8ff,
            transparent: true,
            opacity: 1,
            depthTest: false,
            depthWrite: false,
        });
        const rotationMaterial = new THREE.MeshBasicMaterial({
            color: 0x8b72ff,
            transparent: true,
            opacity: 1,
            depthTest: false,
            depthWrite: false,
        });

        const resizeHandles = [
            { type: "nw", x: -size.x / 2, y: size.y / 2 },
            { type: "n",  x: 0,             y: size.y / 2 },
            { type: "ne", x: size.x / 2,  y: size.y / 2 },
            { type: "e",  x: size.x / 2,  y: 0 },
            { type: "se", x: size.x / 2,  y: -size.y / 2 },
            { type: "s",  x: 0,             y: -size.y / 2 },
            { type: "sw", x: -size.x / 2, y: -size.y / 2 },
            { type: "w",  x: -size.x / 2, y: 0 },
        ];
        resizeHandles.forEach(({ type, x, y }) => {
            const handle = new THREE.Mesh(handleGeometry.clone(), handleMaterial.clone());
            handle.position.set(x, y, handleSize * 0.18);
            handle.renderOrder = 82;
            handle.userData.customizerLayerId = item.id;
            handle.userData.customizerHandleType = type;
            handleGroup.add(handle);
        });

        const rotationStemStart = new THREE.Vector3(0, size.y / 2, handleSize * 0.15);
        const rotationStemEnd = new THREE.Vector3(
            0,
            size.y / 2 + handleSize * 3.2,
            handleSize * 0.15
        );
        const rotationStem = new THREE.Line(
            new THREE.BufferGeometry().setFromPoints([rotationStemStart, rotationStemEnd]),
            new THREE.LineBasicMaterial({
                color: 0x8b72ff,
                depthTest: false,
                depthWrite: false,
            })
        );
        rotationStem.renderOrder = 82;
        handleGroup.add(rotationStem);

        const rotationHandle = new THREE.Mesh(handleGeometry.clone(), rotationMaterial);
        rotationHandle.position.copy(rotationStemEnd);
        rotationHandle.renderOrder = 83;
        rotationHandle.userData.customizerLayerId = item.id;
        rotationHandle.userData.customizerHandleType = "rotate";
        handleGroup.add(rotationHandle);
        target.add(handleGroup);

        item.mesh = mesh;
        item.frame = frame;
        item.handles = handleGroup;
        item.normal = surfaceNormal.clone();
        item.surfacePoint = surfacePoint.clone();
        item.surfaceNormal = surfaceNormal.clone();
        item.position = position.clone();
        item.renderAspect = aspect;
        item.size = size;
        item.target = target;

        if (previousMesh) {
            previousMesh.geometry?.dispose();
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

        if (!options.silent) {
            scheduleRenderLoop();
            renderSelectedPreview();
        }
        return true;
    }


    function updateProjectedLayerDuringDrag(item, point, normal) {
        if (!item?.visibleTexture || !item?.visibleArtwork || !item?.target?.isMesh) return false;

        const surfacePoint = point.clone();
        const surfaceNormal = normal.clone().normalize();
        const target = item.target;
        const position = surfacePoint.clone().addScaledVector(surfaceNormal, 0.008);
        const aspect = Math.max(
            0.15,
            (item.visibleArtwork.visibleWidth || item.visibleTexture.image?.width || 1) /
                Math.max(1, item.visibleArtwork.visibleHeight || item.visibleTexture.image?.height || 1)
        );
        const width = Math.max(0.08, Math.min(1.05, 0.86 * Number(item.layer.width || 0.35)));
        const size = new THREE.Vector3(
            width,
            width / aspect,
            THREE.MathUtils.clamp(width * 0.16, 0.045, 0.085)
        );
        const geometry = new DecalGeometry(
            target,
            position,
            orientation(surfaceNormal, item.layer.rotation),
            size
        );

        if (!geometry.attributes.position?.count) {
            geometry.dispose();
            return false;
        }
        geometry.applyMatrix4(target.matrixWorld.clone().invert());

        if (!item.decalMaterial) {
            item.decalMaterial = new THREE.MeshPhysicalMaterial({
                map: item.visibleTexture,
                color: new THREE.Color("#ffffff"),
                transparent: true,
                opacity: Math.max(0.2, Math.min(1, Number(item.layer.opacity ?? 1))),
                alphaTest: 0.02,
                roughness: 0.62,
                metalness: 0,
                clearcoat: 0.02,
                emissive: new THREE.Color("#ffffff"),
                emissiveMap: item.visibleTexture,
                emissiveIntensity: 0.16,
                depthTest: true,
                depthWrite: false,
                polygonOffset: true,
                polygonOffsetFactor: -5,
                polygonOffsetUnits: -2,
                side: THREE.DoubleSide,
            });
        } else {
            item.decalMaterial.map = item.visibleTexture;
            item.decalMaterial.emissiveMap = item.visibleTexture;
            item.decalMaterial.opacity = Math.max(0.2, Math.min(1, Number(item.layer.opacity ?? 1)));
        }
        const oldMesh = item.mesh;
        const mesh = new THREE.Mesh(geometry, item.decalMaterial);
        mesh.renderOrder = 30 + (Number(item.layer.z_index) || 0);
        mesh.visible = item.layer.visible !== false;
        mesh.userData.customizerLayerId = item.id;
        target.add(mesh);

        // Re-use the existing frame and handles where possible; when the ray
        // moves across separate GLB mesh parts (body, pocket, sleeve), re-parent
        // them to the currently hit mesh before applying its local transform.
        if (item.frame && item.frame.parent !== target) target.add(item.frame);
        if (item.handles && item.handles.parent !== target) target.add(item.handles);
        const targetLocal = target.worldToLocal(position.clone());
        const targetQuaternion = target.getWorldQuaternion(new THREE.Quaternion());
        const worldQuaternion = new THREE.Quaternion().setFromEuler(
            orientation(surfaceNormal, item.layer.rotation)
        );
        const localQuaternion = targetQuaternion.clone().invert().multiply(worldQuaternion);

        if (item.frame) {
            item.frame.position.copy(targetLocal);
            item.frame.quaternion.copy(localQuaternion);
            item.frame.visible = item.id === selectedId && item.layer.visible !== false;
        }
        if (item.handles) {
            item.handles.position.copy(targetLocal);
            item.handles.quaternion.copy(localQuaternion);
            item.handles.visible = item.id === selectedId && item.layer.visible !== false && !item.layer.locked;
        }

        item.mesh = mesh;
        item.normal = surfaceNormal.clone();
        item.surfacePoint = surfacePoint;
        item.surfaceNormal = surfaceNormal.clone();
        item.position = position;
        item.size = size;
        item.renderAspect = aspect;
        item.target = target;

        if (oldMesh) {
            oldMesh.geometry?.dispose();
            oldMesh.parent?.remove(oldMesh);
        }
        render();
        return true;
    }

    function project(item, point, normal, options = {}) {
        if (!item?.artwork?.image || !garmentMeshes.length) return;

        const surfacePoint = point.clone();
        const surfaceNormal = normal.clone().normalize();
        const revision = (item.projectRevision || 0) + 1;
        item.projectRevision = revision;

        const cached = item.visibleArtwork
            ? Promise.resolve(item.visibleArtwork)
            : (item.visibleArtworkPromise || loadTexture(item.artwork.image).then(sourceTexture => {
            const cropped = cropTextureToVisiblePixels(sourceTexture);
            item.visibleArtwork = cropped;
            item.visibleTexture = cropped.texture;
            item.visibleArtworkPromise = Promise.resolve(cropped);
            item.visibleArtworkWidth = cropped.visibleWidth || cropped.texture.image?.width || 0;
            item.visibleArtworkHeight = cropped.visibleHeight || cropped.texture.image?.height || 0;
            return cropped;
        }));

        Promise.resolve(cached).then(cropped => {
            if (!layers.has(item.id) || item.projectRevision !== revision) return;
            item.visibleArtwork = cropped;
            item.visibleTexture = cropped.texture;
            if (!buildProjectedLayer(item, surfacePoint, surfaceNormal, options)) {
                if (!options.silent) status("نمایش لیبل روی این بخش از لباس ممکن نشد.");
            }
        }).catch(() => {
            if (!options.silent) status("تصویر لیبل برای پیش‌نمایش بارگذاری نشد.");
        });
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
            visible: true,
            locked: false,
            flip_x: false,
            flip_y: false,
            z_index: layers.size
                ? Math.max(...Array.from(layers.values()).map(existing => Number(existing.layer.z_index) || 0)) + 1
                : 0,
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
        openSelectedPanel();
        project(item, item.surfacePoint, item.surfaceNormal);
        sync();
        showMobileDragHint();
        document.dispatchEvent(new CustomEvent("babaei:label-added"));
        return true;
    }

    function pointerOnLayerPlane(event, plane) {
        pointerOf(event);
        raycaster.setFromCamera(pointer, camera);
        return raycaster.ray.intersectPlane(plane, new THREE.Vector3());
    }

    function layerPlaneAxes(item, rotation = item.layer.rotation) {
        const quaternion = new THREE.Quaternion().setFromEuler(
            orientation(item.surfaceNormal || item.normal, rotation)
        );
        return {
            right: new THREE.Vector3(1, 0, 0).applyQuaternion(quaternion).normalize(),
            up: new THREE.Vector3(0, 1, 0).applyQuaternion(quaternion).normalize(),
        };
    }

    function layerPlaneCoordinates(point, center, axes) {
        const offset = point.clone().sub(center);
        return {
            x: offset.dot(axes.right),
            y: offset.dot(axes.up),
        };
    }


    function captureLayerVisualState(item) {
        const target = item?.target;
        if (!target || !item?.surfacePoint) return null;

        target.updateWorldMatrix(true, false);
        const snapshot = object => object ? {
            object,
            position: object.position.clone(),
            quaternion: object.quaternion.clone(),
            scale: object.scale.clone(),
        } : null;

        return {
            target,
            center: target.worldToLocal(item.surfacePoint.clone()),
            surfacePoint: item.surfacePoint.clone(),
            surfaceNormal: (item.surfaceNormal || item.normal || frontAxis).clone().normalize(),
            mesh: snapshot(item.mesh),
            frame: snapshot(item.frame),
            handles: snapshot(item.handles),
        };
    }

    function restoreLayerVisualState(state) {
        if (!state) return;
        [state.mesh, state.frame, state.handles].forEach(saved => {
            if (!saved?.object) return;
            saved.object.position.copy(saved.position);
            saved.object.quaternion.copy(saved.quaternion);
            saved.object.scale.copy(saved.scale);
        });
    }

    function applyLayerVisualMove(state, worldDelta) {
        if (!state?.target || !worldDelta || worldDelta.lengthSq() < 1e-12) return;
        state.target.updateWorldMatrix(true, false);

        const startLocal = state.target.worldToLocal(state.surfacePoint.clone());
        const nextLocal = state.target.worldToLocal(state.surfacePoint.clone().add(worldDelta));
        const localDelta = nextLocal.sub(startLocal);

        [state.mesh, state.frame, state.handles].forEach(saved => {
            if (!saved?.object) return;
            saved.object.position.copy(saved.position).add(localDelta);
        });
    }

    function applyLayerVisualScale(state, factor) {
        if (!state || !Number.isFinite(factor)) return;
        const safeFactor = THREE.MathUtils.clamp(factor, 0.05, 4);

        if (state.mesh?.object) {
            const saved = state.mesh;
            saved.object.position.copy(state.center).add(
                saved.position.clone().sub(state.center).multiplyScalar(safeFactor)
            );
            saved.object.quaternion.copy(saved.quaternion);
            saved.object.scale.copy(saved.scale).multiplyScalar(safeFactor);
        }

        [state.frame, state.handles].forEach(saved => {
            if (!saved?.object) return;
            saved.object.position.copy(saved.position);
            saved.object.quaternion.copy(saved.quaternion);
            saved.object.scale.copy(saved.scale).multiplyScalar(safeFactor);
        });
    }

    function applyLayerVisualRotation(state, degrees) {
        if (!state?.target || !Number.isFinite(degrees)) return;
        const inverseWorld = state.target.matrixWorld.clone().invert();
        const localNormal = state.surfaceNormal.clone().transformDirection(inverseWorld).normalize();
        const delta = new THREE.Quaternion().setFromAxisAngle(
            localNormal,
            THREE.MathUtils.degToRad(degrees)
        );

        [state.mesh, state.frame, state.handles].forEach(saved => {
            if (!saved?.object) return;
            saved.object.position.copy(state.center).add(
                saved.position.clone().sub(state.center).applyQuaternion(delta)
            );
            saved.object.quaternion.copy(delta).multiply(saved.quaternion);
            saved.object.scale.copy(saved.scale);
        });
    }

    function beginLayerTransform(event, item, mode, handleType = null) {
        if (!item || item.layer.locked || item.layer.visible === false ||
            !item.surfacePoint || !item.surfaceNormal) {
            return null;
        }

        const normal = item.surfaceNormal.clone().normalize();
        const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, item.surfacePoint);
        const point = pointerOnLayerPlane(event, plane) ||
            (mode === "move" ? item.surfacePoint.clone() : null);
        if (!point) return null;

        const axes = layerPlaneAxes(item);
        const start = layerPlaneCoordinates(point, item.surfacePoint, axes);
        return {
            pointerId: event.pointerId,
            mode,
            layerId: item.id,
            handleType,
            plane,
            axes,
            startPointerPoint: point.clone(),
            startSurfacePoint: item.surfacePoint.clone(),
            startSurfaceNormal: item.surfaceNormal.clone(),
            visual: captureLayerVisualState(item),
            startSide: layerSide(item),
            startAreaId: item.layer.area_id,
            startTarget: item.target,
            startNormal: (item.normal || item.surfaceNormal).clone(),
            startPosition: item.position?.clone() || item.surfacePoint.clone(),
            lastValidPoint: item.surfacePoint.clone(),
            lastValidNormal: item.surfaceNormal.clone(),
            lastValidTarget: item.target,
            startX: start.x,
            startY: start.y,
            startWidth: Number(item.layer.width) || 0.35,
            startHeight: Number(item.layer.height) || 0.25,
            startRotation: Number(item.layer.rotation) || 0,
            startAngle: Math.atan2(start.y, start.x),
        };
    }


    function previewLayerMove(event) {
        const activeDrag = drag;
        const item = activeDrag ? layers.get(activeDrag.layerId) : null;
        if (!activeDrag || !item || !activeDrag.visual) return;

        const fallbackArea = areaById(item.layer.area_id, layerSide(item));
        const hits = garmentHits(event);
        const hit = hits.find(candidate => {
            const candidateSide = surfaceSide(hitNormal(candidate));
            const candidateArea = areaForSurfaceSide(candidateSide, fallbackArea);
            return is3DPrintableArea(candidateArea) &&
                isValidPrintSurface(candidate, candidateArea);
        });
        if (!hit) return;

        const hitNormalVector = hitNormal(hit);
        const hitPoint = hit.point.clone();
        const hitTarget = hit.object;
        const nextSide = surfaceSide(hitNormalVector);
        const nextArea = areaForSurfaceSide(nextSide, fallbackArea);
        if (!nextArea) return;

        // A label may cross the garment's side seam while the user rotates
        // around it. Switch the production print area at the same time as the
        // surface hit; do not keep rejecting the back because the old area was front.
        const previousTarget = item.target;
        const previousSide = item.layer.side;
        const previousAreaId = item.layer.area_id;
        item.target = hitTarget;

        // Reproject on the exact cloth hit in this frame using the cached artwork.
        const projected = updateProjectedLayerDuringDrag(item, hitPoint, hitNormalVector);
        if (!projected) {
            item.target = previousTarget;
            item.layer.side = previousSide;
            item.layer.area_id = previousAreaId;
            return;
        }

        item.layer.side = nextSide;
        item.layer.area_id = nextArea.id;

        activeDrag.lastValidPoint = hitPoint;
        activeDrag.lastValidNormal = hitNormalVector;
        activeDrag.lastValidTarget = hitTarget;
        activeDrag.lastSide = nextSide;
        activeDrag.lastAreaId = nextArea.id;

        render();
    }

    function applyLayerTransform(event) {
        const activeDrag = drag;
        if (!activeDrag) return;

        if (activeDrag.mode === "move") {
            previewLayerMove(event);
            return;
        }

        const item = layers.get(activeDrag.layerId);
        if (!item || item.layer.locked || item.layer.visible === false) return;

        const point = pointerOnLayerPlane(event, activeDrag.plane);
        if (!point) return;

        if (activeDrag.mode === "rotate") {
            const current = layerPlaneCoordinates(point, item.surfacePoint, activeDrag.axes);
            const currentAngle = Math.atan2(current.y, current.x);
            let angleDelta = currentAngle - activeDrag.startAngle;
            if (angleDelta > Math.PI) angleDelta -= Math.PI * 2;
            if (angleDelta < -Math.PI) angleDelta += Math.PI * 2;

            const nextRotation = THREE.MathUtils.clamp(
                activeDrag.startRotation + THREE.MathUtils.radToDeg(angleDelta),
                -180,
                180
            );
            item.layer.rotation = nextRotation;
            applyLayerVisualRotation(
                activeDrag.visual,
                nextRotation - activeDrag.startRotation
            );
            render();
            return;
        }

        if (activeDrag.mode === "resize") {
            const current = layerPlaneCoordinates(point, item.surfacePoint, activeDrag.axes);
            const type = activeDrag.handleType || "";
            const affectsX = type.includes("e") || type.includes("w");
            const affectsY = type.includes("n") || type.includes("s");
            const ratios = [];

            if (affectsX && Math.abs(activeDrag.startX) > 0.001) {
                ratios.push(Math.abs(current.x / activeDrag.startX));
            }
            if (affectsY && Math.abs(activeDrag.startY) > 0.001) {
                ratios.push(Math.abs(current.y / activeDrag.startY));
            }
            if (!ratios.length) return;

            const factor = ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length;
            item.layer.width = THREE.MathUtils.clamp(activeDrag.startWidth * factor, 0.06, 0.98);
            item.layer.height = THREE.MathUtils.clamp(activeDrag.startHeight * factor, 0.04, 0.78);
            applyLayerVisualScale(activeDrag.visual, item.layer.width / activeDrag.startWidth);
            render();
        }
    }

    function finishLayerTransform(activeDrag, event, commit = true) {
        if (!activeDrag) return;
        const item = layers.get(activeDrag.layerId);
        if (!item) return;

        if (!commit) {
            item.layer.width = activeDrag.startWidth;
            item.layer.height = activeDrag.startHeight;
            item.layer.rotation = activeDrag.startRotation;
            item.layer.side = activeDrag.startSide;
            item.layer.area_id = activeDrag.startAreaId ?? item.layer.area_id;
            item.target = activeDrag.startTarget || activeDrag.visual?.target || item.target;
            item.surfacePoint = activeDrag.startSurfacePoint.clone();
            item.surfaceNormal = activeDrag.startSurfaceNormal.clone();
            item.normal = activeDrag.startNormal.clone();
            item.position = activeDrag.startPosition.clone();
            restoreLayerVisualState(activeDrag.visual);
            render();
            return;
        }

        if (activeDrag.mode === "move") {
            if (!activeDrag.lastValidPoint || !activeDrag.lastValidNormal || !activeDrag.lastValidTarget) {
                restoreLayerVisualState(activeDrag.visual);
                render();
                return;
            }
            item.target = activeDrag.lastValidTarget;
            item.layer.side = activeDrag.lastSide || activeDrag.startSide;
            if (activeDrag.lastAreaId != null) item.layer.area_id = activeDrag.lastAreaId;
            const normalized = normalizedGarmentPoint(activeDrag.lastValidPoint);
            if (normalized) {
                item.layer.x = normalized.x;
                item.layer.y = normalized.y;
            }
            item.surfacePoint = activeDrag.lastValidPoint.clone();
            item.surfaceNormal = activeDrag.lastValidNormal.clone();
            item.normal = activeDrag.lastValidNormal.clone();
            item.position = item.surfacePoint.clone().addScaledVector(item.surfaceNormal, 0.008);
            renderSelectedPreview();
            return;
        }

        const validation = validateLayerPlacement(item, placementForLayer(item));
        if (!validation.ok) {
            item.layer.width = activeDrag.startWidth;
            item.layer.height = activeDrag.startHeight;
            item.layer.rotation = activeDrag.startRotation;
            restoreLayerVisualState(activeDrag.visual);
            status(validation.message);
            render();
            return;
        }

        // Rebuild the decal once after the drag. Live movement updates the existing mesh.
        project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
        render();
    }

    function moveSelected(event) {
        const item = layers.get(selectedId);
        if (!item || item.layer.locked || item.layer.visible === false) return false;

        const currentArea = areaById(item.layer.area_id, layerSide(item));
        pointerOf(event);
        raycaster.setFromCamera(pointer, camera);

        // Choose the nearest visible printable surface. When the garment is
        // rotated, this can be its front or back; the label follows the side
        // that the pointer is actually touching rather than staying pinned
        // to the side where it was first created.
        const hits = raycaster.intersectObjects(garmentMeshes, false);
        const hit = hits.find(candidate => {
            const candidateSide = surfaceSide(hitNormal(candidate));
            const candidateArea = areaForSurfaceSide(candidateSide, currentArea);
            return Boolean(candidateArea && isValidPrintSurface(candidate, candidateArea));
        });

        if (!hit) {
            status("لیبل فقط روی سطح قابل چاپ جلو یا پشت بدنه قابل جابه‌جایی است.");
            return false;
        }

        const hitSide = surfaceSide(hitNormal(hit));
        const targetArea = areaForSurfaceSide(hitSide, currentArea);
        if (!targetArea) return false;

        const placement = placementFromPoint(
            targetArea,
            hit.point,
            item.layer.width,
            item.layer.height,
            item.layer.rotation,
        );
        const validation = validateLayerPlacement(item, placement);
        if (!validation.ok) {
            status(validation.message);
            return false;
        }

        item.layer.area_id = targetArea.id;
        item.layer.side = hitSide;
        item.target = hit.object;
        item.normal = hitNormal(hit);
        project(item, hit.point, hitNormal(hit));
        return true;
    }

    function moveSelectedBy(dx, dy) {
        const item = layers.get(selectedId);
        if (!item || item.layer.locked || item.layer.visible === false) return;
        if (!item.target || !item.surfacePoint || !item.surfaceNormal) return;

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

    function compactLayerOrder() {
        const ordered = Array.from(layers.values())
            .sort((a, b) => (Number(a.layer.z_index) || 0) - (Number(b.layer.z_index) || 0));
        ordered.forEach((item, index) => {
            item.layer.z_index = index;
            if (item.mesh) item.mesh.renderOrder = 30 + index;
        });
    }

    function reorderLayers(topFirstIds) {
        const requested = topFirstIds
            .map(id => layers.get(Number(id)))
            .filter(Boolean);
        const included = new Set(requested.map(item => item.id));
        const missing = Array.from(layers.values())
            .filter(item => !included.has(item.id))
            .sort((a, b) => (Number(b.layer.z_index) || 0) - (Number(a.layer.z_index) || 0));
        const orderedTopFirst = [...requested, ...missing];

        orderedTopFirst.forEach((item, index) => {
            item.layer.z_index = orderedTopFirst.length - index - 1;
            if (item.mesh) item.mesh.renderOrder = 30 + item.layer.z_index;
        });

        sync();
        render();
    }

    function cancelLayerDrag() {
        if (!drag) return;
        drag = null;
        pendingDragEvent = null;
        if (dragFrameId) {
            cancelAnimationFrame(dragFrameId);
            dragFrameId = 0;
        }
        if (controls) controls.enabled = true;
    }

    function removeLayerById(layerId) {
        const id = Number(layerId);
        const item = layers.get(id);
        if (!item) return;

        if (drag && selectedId === id) cancelLayerDrag();
        if (selectedId === id) selectedId = null;
        disposeLayer(item);
        layers.delete(id);
        compactLayerOrder();
        sync();
        render();
    }

    function setLayerVisibility(layerId, visible) {
        const item = layers.get(Number(layerId));
        if (!item) return;

        item.layer.visible = Boolean(visible);
        if (item.mesh) item.mesh.visible = item.layer.visible;
        if (item.frame) item.frame.visible = item.layer.visible && item.id === selectedId;
        if (item.handles) item.handles.visible = item.layer.visible && item.id === selectedId;
        if (!item.layer.visible && selectedId === item.id) {
            cancelLayerDrag();
            selectedId = null;
        }
        sync();
        render();
    }

    function setLayerLocked(layerId, locked) {
        const item = layers.get(Number(layerId));
        if (!item) return;

        item.layer.locked = Boolean(locked);
        if (item.layer.locked && selectedId === item.id) {
            cancelLayerDrag();
        }
        sync();
    }

    function selectLayer(layerId) {
        const item = layers.get(Number(layerId));
        if (!item) return;
        selectedId = item.id;
        openSelectedPanel();
        sync();
        render();
    }

    function layerActionButton(action, title, pressed, iconMarkup) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = `studio-layer-action studio-layer-action--${action}`;
        button.dataset.layerAction = action;
        button.title = title;
        button.setAttribute("aria-label", title);
        if (action !== "delete") {
            button.setAttribute("aria-pressed", String(Boolean(pressed)));
        }
        button.innerHTML = iconMarkup;
        return button;
    }

    function renderLayersPanel() {
        const list = document.getElementById("studio-layers-list");
        const count = document.getElementById("studio-layers-count");
        if (!list) return;

        const ordered = Array.from(layers.values())
            .sort((a, b) => (Number(b.layer.z_index) || 0) - (Number(a.layer.z_index) || 0));
        if (count) count.textContent = `${ordered.length.toLocaleString("fa-IR")} لایه`;

        list.replaceChildren();
        if (!ordered.length) {
            const empty = document.createElement("div");
            empty.className = "studio-layers-panel__empty";
            empty.textContent = "هنوز طرحی اضافه نکرده‌ای.";
            list.append(empty);
            return;
        }

        const eyeIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 12s3.4-6.2 9.5-6.2 9.5 6.2 9.5 6.2-3.4 6.2-9.5 6.2S2.5 12 2.5 12Z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="2.8" fill="none" stroke="currentColor" stroke-width="1.7"/></svg>';
        const hiddenIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 6a9.8 9.8 0 0 1 1.4-.1c6.1 0 9.5 6.1 9.5 6.1a15.8 15.8 0 0 1-3 3.6M6.2 6.5C3.8 8.1 2.5 12 2.5 12s3.4 6.2 9.5 6.2c1 0 1.9-.2 2.7-.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.8 9.8a3.1 3.1 0 0 0 4.4 4.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
        const lockIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4.5" y="10" width="15" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 10V7a4 4 0 0 1 8 0v3" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
        const unlockIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4.5" y="10" width="15" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M8 10V7a4 4 0 0 1 7.6-1.8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>';
        const deleteIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m3 0-.8 13H6.8L6 7m4 4v5m4-5v5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

        ordered.forEach((item, index) => {
            const visible = item.layer.visible !== false;
            const locked = Boolean(item.layer.locked);
            const row = document.createElement("div");
            row.className = "studio-layer-row";
            row.dataset.layerId = String(item.id);
            row.setAttribute("role", "listitem");
            row.tabIndex = 0;
            row.draggable = false;
            if (item.id === selectedId) row.classList.add("is-selected");
            if (!visible) row.classList.add("is-hidden-layer");
            if (locked) row.classList.add("is-locked-layer");

            const handle = document.createElement("span");
            handle.className = "studio-layer-drag";
            handle.textContent = "⠿";
            handle.title = "برای تغییر ترتیب بکش";
            handle.setAttribute("role", "button");
            handle.setAttribute("aria-label", `تغییر ترتیب لایه ${index + 1}`);
            handle.tabIndex = 0;
            handle.draggable = true;

            const thumbnail = document.createElement("span");
            thumbnail.className = "studio-layer-row__thumbnail";
            const image = document.createElement("img");
            image.alt = "";
            image.loading = "lazy";
            if (item.artwork?.image) {
                image.src = item.artwork.image;
            } else {
                image.hidden = true;
                thumbnail.classList.add("is-empty");
            }
            image.addEventListener("error", () => {
                image.hidden = true;
                thumbnail.classList.add("is-empty");
            }, { once: true });
            thumbnail.append(image);

            const copy = document.createElement("span");
            copy.className = "studio-layer-row__copy";
            const name = document.createElement("strong");
            name.textContent = String(item.layer.text || item.artwork?.name || "لیبل");
            const type = document.createElement("small");
            type.textContent = item.artwork?.is_text ? "متن" : "تصویر";
            copy.append(name, type);

            const actions = document.createElement("span");
            actions.className = "studio-layer-row__actions";
            actions.append(
                layerActionButton(
                    "visibility",
                    visible ? "مخفی کردن لایه" : "نمایش لایه",
                    visible,
                    visible ? eyeIcon : hiddenIcon
                ),
                layerActionButton(
                    "lock",
                    locked ? "باز کردن قفل لایه" : "قفل کردن لایه",
                    locked,
                    locked ? lockIcon : unlockIcon
                ),
                layerActionButton("delete", "حذف لایه", false, deleteIcon)
            );

            row.append(handle, thumbnail, copy, actions);
            list.append(row);
        });
    }

    let selectedPreviewRevision = 0;

    async function selectedPreviewImage(src) {
        if (!src) return null;
        if (!selectedPreviewImages.has(src)) {
            selectedPreviewImages.set(src, imageFromSource(src).catch(() => null));
        }
        return selectedPreviewImages.get(src);
    }

    async function renderSelectedPreview() {
        const canvas = document.getElementById("studio-selected-preview");
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();
        if (rect.width < 2 || rect.height < 2) return;

        if (drag?.mode === "move") return;
        const token = ++selectedPreviewRevision;
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.max(1, Math.round(rect.width * ratio));
        canvas.height = Math.max(1, Math.round(rect.height * ratio));

        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, rect.width, rect.height);
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, rect.width, rect.height);

        // Subtle alignment guides keep the preview readable without adding a garment mockup.
        ctx.save();
        ctx.strokeStyle = "rgba(30,30,35,.055)";
        ctx.lineWidth = 1;
        for (let x = 18; x < rect.width; x += 24) {
            ctx.beginPath();
            ctx.moveTo(x, 10);
            ctx.lineTo(x, rect.height - 10);
            ctx.stroke();
        }
        for (let y = 18; y < rect.height; y += 24) {
            ctx.beginPath();
            ctx.moveTo(10, y);
            ctx.lineTo(rect.width - 10, y);
            ctx.stroke();
        }
        ctx.restore();

        const selected = layers.get(selectedId);
        const side = selected ? layerSide(selected) : active2DSide;
        const visibleItems = Array.from(layers.values())
            .filter(item => layerSide(item) === side && item.layer.visible !== false)
            .sort((a, b) => (Number(a.layer.z_index) || 0) - (Number(b.layer.z_index) || 0));

        const padding = 18;
        const usableWidth = Math.max(1, rect.width - padding * 2);
        const usableHeight = Math.max(1, rect.height - padding * 2);

        for (const item of visibleItems) {
            const previewOverride = selectedPreviewDrag?.layerId === item.id
                ? selectedPreviewDrag.previewNormalized
                : null;
            const normalized = previewOverride || normalizedGarmentPoint(item.surfacePoint || item.position) || {
                x: Number(item.layer.x ?? 0.5),
                y: Number(item.layer.y ?? 0.5),
            };
            const centerX = padding + THREE.MathUtils.clamp(normalized.x, 0, 1) * usableWidth;
            const centerY = padding + THREE.MathUtils.clamp(normalized.y, 0, 1) * usableHeight;
            const image = await selectedPreviewImage(item.artwork?.image || "");
            if (token !== selectedPreviewRevision) return;

            const aspect = Math.max(
                0.15,
                image
                    ? (image.naturalWidth || image.width) / Math.max(1, image.naturalHeight || image.height)
                    : 2.2
            );
            const drawWidth = Math.max(16, Math.min(
                usableWidth * 0.56,
                usableWidth * Number(item.layer.width || 0.35) * 0.88
            ));
            const drawHeight = Math.min(usableHeight * 0.58, drawWidth / aspect);

            ctx.save();
            ctx.translate(centerX, centerY);
            ctx.rotate(THREE.MathUtils.degToRad(Number(item.layer.rotation) || 0));
            ctx.scale(item.layer.flip_x ? -1 : 1, item.layer.flip_y ? -1 : 1);
            if (image) {
                ctx.globalAlpha = Number(item.layer.opacity ?? 1);
                ctx.drawImage(image, -drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);
            } else {
                ctx.fillStyle = item.layer.color || "#252525";
                ctx.font = "700 15px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(String(item.layer.text || item.artwork?.name || "TEXT"), 0, 0, drawWidth);
            }
            ctx.restore();

            if (item.id !== selectedId) continue;

            ctx.save();
            ctx.translate(centerX, centerY);
            ctx.rotate(THREE.MathUtils.degToRad(Number(item.layer.rotation) || 0));
            ctx.strokeStyle = item.layer.locked ? "#9ca3af" : "#8874ff";
            ctx.lineWidth = 1.4;
            ctx.strokeRect(-drawWidth / 2, -drawHeight / 2, drawWidth, drawHeight);

            if (!item.layer.locked) {
                const grips = [
                    [-drawWidth / 2, -drawHeight / 2],
                    [0, -drawHeight / 2],
                    [drawWidth / 2, -drawHeight / 2],
                    [drawWidth / 2, 0],
                    [drawWidth / 2, drawHeight / 2],
                    [0, drawHeight / 2],
                    [-drawWidth / 2, drawHeight / 2],
                    [-drawWidth / 2, 0],
                ];
                grips.forEach(([x, y]) => {
                    ctx.fillStyle = "#ffffff";
                    ctx.strokeStyle = "#8874ff";
                    ctx.lineWidth = 1.2;
                    ctx.fillRect(x - 6, y - 6, 12, 12);
                    ctx.strokeRect(x - 6, y - 6, 12, 12);
                });

                ctx.beginPath();
                ctx.moveTo(0, -drawHeight / 2);
                ctx.lineTo(0, -drawHeight / 2 - 17);
                ctx.strokeStyle = "#8874ff";
                ctx.stroke();

                ctx.beginPath();
                ctx.arc(0, -drawHeight / 2 - 20, 9, 0, Math.PI * 2);
                ctx.fillStyle = "#8874ff";
                ctx.fill();
                ctx.fillStyle = "#ffffff";
                ctx.font = "10px sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText("↻", 0, -drawHeight / 2 - 20);
            }
            ctx.restore();
        }

        const empty = document.getElementById("studio-selected-preview-empty");
        if (empty) empty.hidden = Boolean(selected);
        const sideLabel = document.getElementById("studio-selected-side");
        if (sideLabel) sideLabel.textContent = side === "back" ? "نمای پشت" : "نمای جلو";

        const name = document.getElementById("studio-selected-layer-name");
        const meta = document.getElementById("studio-selected-layer-meta");
        if (name) name.textContent = selected
            ? String(selected.layer.text || selected.artwork?.name || "لیبل")
            : "لایه‌ای انتخاب نشده";
        const scaleValue = document.getElementById("studio-selected-scale-value");
        if (scaleValue) {
            scaleValue.textContent = selected
                ? Math.round(Number(selected.layer.width || 0.35) * 100) + "٪"
                : "—";
        }
        if (meta) {
            if (!selected) {
                meta.textContent = "از فهرست بالا یک طرح انتخاب کن.";
            } else {
                const state = selected.layer.locked ? "قفل‌شده" : "قابل ویرایش";
                const layerSideLabel = layerSide(selected) === "back" ? "پشت لباس" : "جلوی لباس";
                meta.textContent = `${layerSideLabel} · ${state} · ${Math.round(Number(selected.layer.width || 0.35) * 100)}٪`;
            }
        }

        document.querySelectorAll("#studio-selected-actions [data-selected-action], .studio-selected-scale-controls [data-selected-action]").forEach(button => {
            const action = button.dataset.selectedAction;
            const requiresEditable = ["flip-x", "flip-y", "scale-up", "scale-down"].includes(action);
            button.disabled = !selected || (requiresEditable && Boolean(selected.layer.locked));
        });
    }


    function selectedPreviewLayout(item, rect) {
        if (!item || !rect) return null;
        const previewOverride = selectedPreviewDrag?.layerId === item.id
            ? selectedPreviewDrag.previewNormalized
            : null;
        const normalized = previewOverride || normalizedGarmentPoint(item.surfacePoint || item.position) || {
            x: Number(item.layer.x ?? 0.5),
            y: Number(item.layer.y ?? 0.5),
        };
        const padding = 18;
        const usableWidth = Math.max(1, rect.width - padding * 2);
        const usableHeight = Math.max(1, rect.height - padding * 2);
        const aspect = Math.max(
            0.15,
            Number(item.renderAspect) ||
                (Number(item.visibleArtworkWidth) / Math.max(1, Number(item.visibleArtworkHeight))) ||
                2.2
        );
        const drawWidth = Math.max(16, Math.min(
            usableWidth * 0.56,
            usableWidth * Number(item.layer.width || 0.35) * 0.88
        ));
        const drawHeight = Math.min(usableHeight * 0.58, drawWidth / aspect);

        return {
            centerX: padding + THREE.MathUtils.clamp(normalized.x, 0, 1) * usableWidth,
            centerY: padding + THREE.MathUtils.clamp(normalized.y, 0, 1) * usableHeight,
            usableWidth,
            usableHeight,
            drawWidth,
            drawHeight,
            rotation: THREE.MathUtils.degToRad(Number(item.layer.rotation) || 0),
            normalized,
        };
    }

    function selectedPreviewHitTest(item, layout, x, y, includeHandles) {
        if (!layout) return null;
        const dx = x - layout.centerX;
        const dy = y - layout.centerY;
        const cosine = Math.cos(layout.rotation);
        const sine = Math.sin(layout.rotation);
        const localX = cosine * dx + sine * dy;
        const localY = -sine * dx + cosine * dy;
        const halfWidth = layout.drawWidth / 2;
        const halfHeight = layout.drawHeight / 2;

        if (includeHandles && !item.layer.locked) {
            const rotateY = -halfHeight - 20;
            if (Math.hypot(localX, localY - rotateY) <= 16) {
                return { mode: "rotate", handleType: "rotate" };
            }

            const grips = [
                { type: "nw", x: -halfWidth, y: -halfHeight },
                { type: "n",  x: 0,           y: -halfHeight },
                { type: "ne", x: halfWidth,   y: -halfHeight },
                { type: "e",  x: halfWidth,   y: 0 },
                { type: "se", x: halfWidth,   y: halfHeight },
                { type: "s",  x: 0,           y: halfHeight },
                { type: "sw", x: -halfWidth, y: halfHeight },
                { type: "w",  x: -halfWidth, y: 0 },
            ];
            for (const grip of grips) {
                if (Math.hypot(localX - grip.x, localY - grip.y) <= 15) {
                    return { mode: "resize", handleType: grip.type };
                }
            }
        }

        if (
            Math.abs(localX) <= halfWidth + 10 &&
            Math.abs(localY) <= halfHeight + 10
        ) {
            return { mode: "move", handleType: null };
        }
        return null;
    }

    function selectedPreviewPointer(event, canvas) {
        const rect = canvas.getBoundingClientRect();
        return {
            x: event.clientX - rect.left,
            y: event.clientY - rect.top,
            rect: { width: rect.width, height: rect.height },
        };
    }

    function applySelectedPreviewDrag(event) {
        const active = selectedPreviewDrag;
        const item = active ? layers.get(active.layerId) : null;
        const canvas = document.getElementById("studio-selected-preview");
        if (!active || !item || !canvas) return;

        const pointerPosition = selectedPreviewPointer(event, canvas);
        const x = pointerPosition.x;
        const y = pointerPosition.y;

        if (active.mode === "move") {
            const normalized = {
                x: THREE.MathUtils.clamp(
                    active.startNormalized.x + (x - active.startPointer.x) / active.usableWidth,
                    0.02,
                    0.98
                ),
                y: THREE.MathUtils.clamp(
                    active.startNormalized.y + (y - active.startPointer.y) / active.usableHeight,
                    0.02,
                    0.98
                ),
            };
            const side = layerSide(item);
            const area = areaById(item.layer.area_id, side);
            const hit = garmentSurfaceHitAtPlacement(normalized.x, normalized.y, side);
            if (!hit || !isValidPrintSurface(hit, area)) return;

            active.previewNormalized = normalized;
            active.previewPoint = hit.point.clone();
            active.previewNormal = hitNormal(hit);
            active.previewTarget = hit.object;
            applyLayerVisualMove(
                active.visual,
                hit.point.clone().sub(active.startSurfacePoint)
            );
        } else if (active.mode === "resize") {
            const dx = x - active.layout.centerX;
            const dy = y - active.layout.centerY;
            const cosine = Math.cos(active.layout.rotation);
            const sine = Math.sin(active.layout.rotation);
            const localX = cosine * dx + sine * dy;
            const localY = -sine * dx + cosine * dy;
            const type = active.handleType || "";
            const anchors = {
                nw: [-active.layout.drawWidth / 2, -active.layout.drawHeight / 2],
                n:  [0, -active.layout.drawHeight / 2],
                ne: [active.layout.drawWidth / 2, -active.layout.drawHeight / 2],
                e:  [active.layout.drawWidth / 2, 0],
                se: [active.layout.drawWidth / 2, active.layout.drawHeight / 2],
                s:  [0, active.layout.drawHeight / 2],
                sw: [-active.layout.drawWidth / 2, active.layout.drawHeight / 2],
                w:  [-active.layout.drawWidth / 2, 0],
            };
            const anchor = anchors[type];
            if (!anchor) return;

            const ratios = [];
            if ((type.includes("e") || type.includes("w")) && Math.abs(anchor[0]) > 1) {
                ratios.push(Math.abs(localX / anchor[0]));
            }
            if ((type.includes("n") || type.includes("s")) && Math.abs(anchor[1]) > 1) {
                ratios.push(Math.abs(localY / anchor[1]));
            }
            if (!ratios.length) return;

            const factor = THREE.MathUtils.clamp(
                ratios.reduce((sum, ratio) => sum + ratio, 0) / ratios.length,
                0.18,
                3
            );
            item.layer.width = THREE.MathUtils.clamp(active.startWidth * factor, 0.06, 0.98);
            item.layer.height = THREE.MathUtils.clamp(active.startHeight * factor, 0.04, 0.78);
            applyLayerVisualScale(active.visual, item.layer.width / active.startWidth);
        } else if (active.mode === "rotate") {
            const currentAngle = Math.atan2(y - active.layout.centerY, x - active.layout.centerX);
            let angleDelta = currentAngle - active.startAngle;
            if (angleDelta > Math.PI) angleDelta -= Math.PI * 2;
            if (angleDelta < -Math.PI) angleDelta += Math.PI * 2;
            item.layer.rotation = THREE.MathUtils.clamp(
                active.startRotation + THREE.MathUtils.radToDeg(angleDelta),
                -180,
                180
            );
            applyLayerVisualRotation(active.visual, item.layer.rotation - active.startRotation);
        }

        renderSelectedPreview();
        render();
    }

    function finishSelectedPreviewDrag(commit = true) {
        const active = selectedPreviewDrag;
        if (!active) return;
        const item = layers.get(active.layerId);

        if (selectedPreviewFrameId) {
            cancelAnimationFrame(selectedPreviewFrameId);
            selectedPreviewFrameId = 0;
        }
        pendingSelectedPreviewEvent = null;

        if (!item) {
            selectedPreviewDrag = null;
            return;
        }

        if (!commit) {
            item.layer.width = active.startWidth;
            item.layer.height = active.startHeight;
            item.layer.rotation = active.startRotation;
            restoreLayerVisualState(active.visual);
            selectedPreviewDrag = null;
            render();
            sync();
            return;
        }

        if (active.mode === "move") {
            if (active.previewPoint && active.previewNormal && active.previewTarget) {
                item.layer.x = active.previewNormalized.x;
                item.layer.y = active.previewNormalized.y;
                item.target = active.previewTarget;
                project(item, active.previewPoint, active.previewNormal);
            } else {
                restoreLayerVisualState(active.visual);
            }
        } else {
            const validation = validateLayerPlacement(item, placementForLayer(item));
            if (!validation.ok) {
                item.layer.width = active.startWidth;
                item.layer.height = active.startHeight;
                item.layer.rotation = active.startRotation;
                restoreLayerVisualState(active.visual);
                status(validation.message);
            } else {
                project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
            }
        }

        selectedPreviewDrag = null;
        render();
        sync();
    }

    function bindSelectedPreviewInteraction() {
        const canvas = document.getElementById("studio-selected-preview");
        if (!canvas || canvas.dataset.bound === "1") return;
        canvas.dataset.bound = "1";

        canvas.addEventListener("pointerdown", event => {
            if (event.button !== 0 || selectedPreviewDrag) return;
            const pointerPosition = selectedPreviewPointer(event, canvas);
            const rect = pointerPosition.rect;
            const selected = layers.get(selectedId);
            const side = selected ? layerSide(selected) : active2DSide;
            const visibleItems = Array.from(layers.values())
                .filter(item => layerSide(item) === side && item.layer.visible !== false)
                .sort((a, b) => (Number(a.layer.z_index) || 0) - (Number(b.layer.z_index) || 0));

            let match = null;
            for (let index = visibleItems.length - 1; index >= 0; index -= 1) {
                const item = visibleItems[index];
                const layout = selectedPreviewLayout(item, rect);
                const hit = selectedPreviewHitTest(
                    item,
                    layout,
                    pointerPosition.x,
                    pointerPosition.y,
                    item.id === selectedId
                );
                if (hit) {
                    match = { item, layout, hit };
                    break;
                }
            }
            if (!match) return;

            const item = match.item;
            if (item.id !== selectedId) {
                selectedId = item.id;
                openSelectedPanel();
            }
            if (item.layer.locked || item.layer.visible === false) {
                sync();
                status("این لایه قفل است؛ برای ویرایش ابتدا قفل را باز کن.");
                return;
            }

            const normalized = normalizedGarmentPoint(item.surfacePoint || item.position) || {
                x: Number(item.layer.x ?? 0.5),
                y: Number(item.layer.y ?? 0.5),
            };
            selectedPreviewDrag = {
                pointerId: event.pointerId,
                layerId: item.id,
                mode: match.hit.mode,
                handleType: match.hit.handleType,
                layout: match.layout,
                visual: captureLayerVisualState(item),
                startPointer: { x: pointerPosition.x, y: pointerPosition.y },
                startNormalized: { x: normalized.x, y: normalized.y },
                previewNormalized: { x: normalized.x, y: normalized.y },
                usableWidth: match.layout.usableWidth,
                usableHeight: match.layout.usableHeight,
                startSurfacePoint: item.surfacePoint.clone(),
                previewPoint: item.surfacePoint.clone(),
                previewNormal: item.surfaceNormal.clone(),
                previewTarget: item.target,
                startWidth: Number(item.layer.width) || 0.35,
                startHeight: Number(item.layer.height) || 0.25,
                startRotation: Number(item.layer.rotation) || 0,
                startAngle: Math.atan2(
                    pointerPosition.y - match.layout.centerY,
                    pointerPosition.x - match.layout.centerX
                ),
            };

            canvas.style.cursor = "grabbing";
            canvas.setPointerCapture(event.pointerId);
            event.preventDefault();
            sync();
            renderSelectedPreview();
        });

        canvas.addEventListener("pointermove", event => {
            if (!selectedPreviewDrag || selectedPreviewDrag.pointerId !== event.pointerId) return;
            event.preventDefault();
            pendingSelectedPreviewEvent = event;
            if (selectedPreviewFrameId) return;

            selectedPreviewFrameId = requestAnimationFrame(() => {
                selectedPreviewFrameId = 0;
                const latest = pendingSelectedPreviewEvent;
                pendingSelectedPreviewEvent = null;
                if (latest && selectedPreviewDrag?.pointerId === latest.pointerId) {
                    applySelectedPreviewDrag(latest);
                }
            });
        });

        ["pointerup", "pointercancel", "lostpointercapture"].forEach(type => {
            canvas.addEventListener(type, event => {
                if (!selectedPreviewDrag || selectedPreviewDrag.pointerId !== event.pointerId) return;
                const commit = type === "pointerup";
                if (pendingSelectedPreviewEvent?.pointerId === event.pointerId) {
                    applySelectedPreviewDrag(pendingSelectedPreviewEvent);
                }
                finishSelectedPreviewDrag(commit);
                canvas.style.cursor = "";
            });
        });
    }

    function bindLayersPanel() {
        const list = document.getElementById("studio-layers-list");
        if (!list || list.dataset.bound === "1") return;
        list.dataset.bound = "1";

        list.addEventListener("click", event => {
            const actionButton = event.target.closest("[data-layer-action]");
            const row = event.target.closest("[data-layer-id]");
            if (!row || !list.contains(row)) return;

            const id = Number(row.dataset.layerId);
            if (actionButton) {
                event.preventDefault();
                event.stopPropagation();
                const item = layers.get(id);
                if (!item) return;
                const action = actionButton.dataset.layerAction;
                if (action === "visibility") {
                    setLayerVisibility(id, item.layer.visible === false);
                } else if (action === "lock") {
                    setLayerLocked(id, !item.layer.locked);
                } else if (action === "delete") {
                    removeLayerById(id);
                }
                return;
            }

            selectLayer(id);
        });

        list.addEventListener("keydown", event => {
            const row = event.target.closest("[data-layer-id]");
            if (!row) return;
            if ((event.key === "Enter" || event.key === " ") && event.target === row) {
                event.preventDefault();
                selectLayer(Number(row.dataset.layerId));
                return;
            }
            if (!event.altKey || !["ArrowUp", "ArrowDown"].includes(event.key)) return;

            const rows = Array.from(list.querySelectorAll("[data-layer-id]"));
            const currentIndex = rows.indexOf(row);
            const nextIndex = currentIndex + (event.key === "ArrowUp" ? -1 : 1);
            if (nextIndex < 0 || nextIndex >= rows.length) return;
            event.preventDefault();
            const moving = rows[currentIndex];
            const target = rows[nextIndex];
            list.insertBefore(moving, event.key === "ArrowUp" ? target : target.nextSibling);
            reorderLayers(Array.from(list.querySelectorAll("[data-layer-id]")).map(node => Number(node.dataset.layerId)));
            row.focus();
        });

        let draggedId = null;
        list.addEventListener("dragstart", event => {
            const handle = event.target.closest(".studio-layer-drag");
            const row = handle?.closest("[data-layer-id]");
            if (!handle || !row) {
                event.preventDefault();
                return;
            }
            draggedId = Number(row.dataset.layerId);
            row.classList.add("is-dragging");
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", String(draggedId));
            }
        });

        list.addEventListener("dragover", event => {
            if (draggedId === null || !event.target.closest("[data-layer-id]")) return;
            event.preventDefault();
            if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
        });

        list.addEventListener("drop", event => {
            const targetRow = event.target.closest("[data-layer-id]");
            if (draggedId === null || !targetRow) return;
            event.preventDefault();
            const movingRow = list.querySelector(`[data-layer-id="${draggedId}"]`);
            if (!movingRow || movingRow === targetRow) return;

            const bounds = targetRow.getBoundingClientRect();
            const insertAfter = event.clientY > bounds.top + bounds.height / 2;
            list.insertBefore(movingRow, insertAfter ? targetRow.nextSibling : targetRow);
            reorderLayers(Array.from(list.querySelectorAll("[data-layer-id]")).map(node => Number(node.dataset.layerId)));
        });

        list.addEventListener("dragend", () => {
            list.querySelectorAll(".is-dragging").forEach(row => row.classList.remove("is-dragging"));
            draggedId = null;
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
                locked: Boolean(selected?.layer?.locked),
                visible: selected ? selected.layer.visible !== false : false,
                zIndex: selected ? Number(selected.layer.z_index) || 0 : null,
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
            const layerVisible = item.layer.visible !== false;
            const selectedVisible = item.id === selectedId && layerVisible;
            if (item.mesh) item.mesh.visible = layerVisible;
            if (item.frame) item.frame.visible = selectedVisible;
            if (item.handles) item.handles.visible = selectedVisible && !item.layer.locked;
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
        renderLayersPanel();
        renderSelectedPreview();
        if (!document.getElementById("designer-2d-stage")?.classList.contains("is-hidden")) {
            render2DPreview();
        }
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
        let view = await resolve2DPatternView(side);
        if (!view?.background) return null;

        let background;
        try {
            background = await imageFromSource(view.background);
        } catch (databaseImageError) {
            console.warn("Configured 2D canvas failed; trying generated pattern SVG.", databaseImageError);
            const fallbackView = await resolve2DPatternView(side, { forceGenerated: true });
            if (!fallbackView?.background || fallbackView.background === view.background) {
                throw databaseImageError;
            }
            view = fallbackView;
            background = await imageFromSource(view.background);
        }
        const canvas = document.createElement("canvas");
        const scale = Math.min(1, 1800 / Math.max(background.naturalWidth || background.width, background.naturalHeight || background.height));
        canvas.width = Math.max(1, Math.round((background.naturalWidth || background.width) * scale));
        canvas.height = Math.max(1, Math.round((background.naturalHeight || background.height) * scale));
        const ctx = canvas.getContext("2d");
        ctx.drawImage(background, 0, 0, canvas.width, canvas.height);

        const viewAreas = view.areas || [];
        const areaByIdLocal = id => viewAreas.find(area => Number(area.id) === Number(id));
        const sideLayers = Array.from(layers.values())
            .filter(item => layerSide(item) === side && item.layer.visible !== false)
            .sort((a, b) => (Number(a.layer.z_index) || 0) - (Number(b.layer.z_index) || 0));

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
            ctx.scale(item.layer.flip_x ? -1 : 1, item.layer.flip_y ? -1 : 1);
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

    function draw2DStudioGrid(context, width, height, ratio = 1) {
        const step = 24 * Math.max(1, Math.min(ratio, 2));
        context.save();
        context.lineWidth = 1;
        for (let x = 0, index = 0; x <= width; x += step, index += 1) {
            context.beginPath();
            context.moveTo(Math.round(x) + 0.5, 0);
            context.lineTo(Math.round(x) + 0.5, height);
            context.strokeStyle = index % 5 === 0
                ? "rgba(117, 119, 124, 0.18)"
                : "rgba(117, 119, 124, 0.075)";
            context.stroke();
        }
        for (let y = 0, index = 0; y <= height; y += step, index += 1) {
            context.beginPath();
            context.moveTo(0, Math.round(y) + 0.5);
            context.lineTo(width, Math.round(y) + 0.5);
            context.strokeStyle = index % 5 === 0
                ? "rgba(117, 119, 124, 0.18)"
                : "rgba(117, 119, 124, 0.075)";
            context.stroke();
        }
        context.restore();
    }

    let active2DSide = "front";
    let previewRenderToken = 0;

    async function render2DPreview() {
        const token = ++previewRenderToken;
        const previewCanvas = document.getElementById("designer-canvas");
        const loading = document.getElementById("stage-loading");
        if (!previewCanvas) return;
        if (loading) {
            loading.textContent = "در حال آماده‌سازی نمای دوبعدی…";
            loading.classList.remove("is-hidden");
        }
        try {
            const blob = await build2DPreview(active2DSide);
            if (token !== previewRenderToken) return;
            if (!blob) {
                if (loading) {
                    loading.textContent = "الگوی دوبعدی این مدل هنوز تولید نشده است؛ اسکریپت scripts/garment-patterns را اجرا کنید.";
                    loading.classList.remove("is-hidden");
                }
                return;
            }
            const imageUrl = URL.createObjectURL(blob);
            try {
                const image = await imageFromSource(imageUrl);
                if (token !== previewRenderToken) return;

                // Wait for layout after the 2D panel becomes visible.
                let rect = null;
                for (let attempt = 0; attempt < 4; attempt += 1) {
                    await new Promise(resolve => requestAnimationFrame(resolve));
                    if (token !== previewRenderToken) return;
                    rect = previewCanvas.getBoundingClientRect();
                    if (rect.width > 1 && rect.height > 1) break;
                }
                if (!rect || rect.width <= 1 || rect.height <= 1) {
                    throw new Error("2D preview stage has no visible layout size.");
                }

                const ratio = Math.min(window.devicePixelRatio || 1, 2);
                const width = Math.max(1, Math.round(rect.width * ratio));
                const height = Math.max(1, Math.round(rect.height * ratio));
                previewCanvas.width = width;
                previewCanvas.height = height;
                const context = previewCanvas.getContext("2d");
                if (!context) throw new Error("2D preview canvas context is unavailable.");
                context.clearRect(0, 0, width, height);
                context.fillStyle = "#f5f3ee";
                context.fillRect(0, 0, width, height);
                draw2DStudioGrid(context, width, height, ratio);

                // Preserve the pattern sheet's aspect ratio and keep all pieces visible.
                const padding = 18 * ratio;
                const availableWidth = Math.max(1, width - padding * 2);
                const availableHeight = Math.max(1, height - padding * 2);
                const scale = Math.min(availableWidth / image.width, availableHeight / image.height);
                const drawWidth = image.width * scale;
                const drawHeight = image.height * scale;
                context.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
                if (loading) loading.classList.add("is-hidden");
            } finally {
                URL.revokeObjectURL(imageUrl);
            }
        } catch (error) {
            console.error("2D garment preview failed", error);
            if (loading) {
                loading.textContent = "نمای دوبعدی بارگذاری نشد.";
                loading.classList.remove("is-hidden");
            }
        }
    }

    function setStudioView(mode) {
        const shell = document.getElementById("stage-shell");
        const twoD = document.getElementById("designer-2d-stage");
        const threeD = document.getElementById("designer-3d-stage");
        if (!shell || !twoD || !threeD) return;
        const requestedView = ["2d", "split", "3d"].includes(mode) ? mode : preferredStudioView;
        if (garmentType !== "mug") {
            preferredStudioView = requestedView;
            try {
                window.localStorage.setItem(studioViewStorageKey, preferredStudioView);
            } catch (error) {
                // Storage may be disabled; keep the in-memory preference.
            }
        }
        const view = garmentType === "mug" ? "3d" : preferredStudioView;
        const switcher = document.getElementById("studio-view-switcher");
        if (switcher) switcher.hidden = garmentType === "mug";
        shell.classList.toggle("stage-shell--split", view === "split");
        shell.classList.toggle("stage-shell--2d", view === "2d");
        shell.classList.toggle("stage-shell--3d", view === "3d");
        twoD.classList.toggle("is-hidden", view === "3d");
        threeD.classList.toggle("is-hidden", view === "2d");
        bindLayersPanel();

        document.querySelectorAll("[data-studio-view]").forEach(button => {
            const active = button.dataset.studioView === view;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });

        if (view !== "3d") {
            requestAnimationFrame(() => requestAnimationFrame(() => render2DPreview()));
        } else {
            // Cancel any pending 2D render while the panel is hidden.
            previewRenderToken += 1;
        }
        if (view !== "2d") requestAnimationFrame(() => resize());
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
        return Array.from(layers.values())
            .sort((a, b) => (Number(a.layer.z_index) || 0) - (Number(b.layer.z_index) || 0))
            .map(item => {
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
                    visible: item.layer.visible !== false,
                    locked: Boolean(item.layer.locked),
                    flip_x: Boolean(item.layer.flip_x),
                    flip_y: Boolean(item.layer.flip_y),
                    z_index: Number(item.layer.z_index) || 0,
                    text: item.artwork?.is_text
                        ? String(item.layer.text || item.artwork.name || "")
                        : null,
                    text_style: item.artwork?.is_text
                        ? normalizeTextStyle(item.layer.text_style || item.artwork.text_style || {})
                        : null,
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


    // Scene backdrops are intentionally client-only. They are applied to the stage
    // element (behind the transparent WebGL canvas), never added to the design
    // payload and never uploaded to the server or database.
    let sceneBackdropMode = "color";
    let sceneBackdropColor = "#2b2b2e";
    let sceneBackdropObjectUrl = null;
    let sceneBackdropFileName = "";
    let sceneBackdropLoadToken = 0;
    const SCENE_BACKDROP_MAX_BYTES = 15 * 1024 * 1024;

    function applySceneBackdrop() {
        if (!stage) return;

        let background = "#f2f3f5";
        if (sceneBackdropMode === "color") {
            background = sceneBackdropColor;
        } else if (sceneBackdropMode === "image" && sceneBackdropObjectUrl) {
            background = `#f2f3f5 url("${sceneBackdropObjectUrl}") center / cover no-repeat`;
        }

        // The renderer uses alpha:true. Keeping this background on the DOM stage
        // means it is visible in the editor but remains outside saved design data.
        stage.style.setProperty("background", background, "important");
    }

    function syncSceneBackdropPanel() {
        const workspace = root.closest(".customizer-workspace--premium") || root;
        const heading = document.getElementById("studio-layers-heading");
        const count = document.getElementById("studio-layers-count");
        const layers = document.getElementById("studio-layers-list");
        const footer = document.querySelector(".studio-layers-panel__footer");
        const selectedPanel = document.getElementById("studio-selected-panel");
        const scenePanel = document.getElementById("studio-scene-panel");
        const colorControls = document.getElementById("studio-scene-color-controls");
        const imageControls = document.getElementById("studio-scene-image-controls");
        const imageName = document.getElementById("studio-scene-image-name");
        const removeImage = document.getElementById("studio-scene-image-remove");
        const colorInput = document.getElementById("studio-scene-color-input");
        const uploadDropzone = document.getElementById("studio-scene-upload-dropzone");

        const activeTab = workspace.dataset.studioPanelTab || "selected";
        const sceneActive = activeTab === "scene";

        // The layer stack is shared by both tabs and remains visible at the top.
        if (heading) heading.textContent = "لایه‌ها";
        if (count) count.hidden = false;
        if (layers) layers.hidden = false;
        if (footer) footer.hidden = false;
        if (selectedPanel) selectedPanel.hidden = sceneActive;
        if (scenePanel) scenePanel.hidden = !sceneActive;

        document.querySelectorAll("[data-studio-panel-tab]").forEach(button => {
            const active = button.dataset.studioPanelTab === activeTab;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-selected", String(active));
            button.tabIndex = active ? 0 : -1;
        });

        document.querySelectorAll("[data-scene-backdrop-mode]").forEach(button => {
            const active = button.dataset.sceneBackdropMode === sceneBackdropMode;
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });

        if (colorControls) colorControls.hidden = sceneBackdropMode !== "color";
        if (imageControls) imageControls.hidden = sceneBackdropMode !== "image";

        document.querySelectorAll("[data-scene-color]").forEach(button => {
            const active = button.dataset.sceneColor?.toLowerCase() === sceneBackdropColor.toLowerCase();
            button.classList.toggle("is-active", active);
            button.setAttribute("aria-pressed", String(active));
        });

        if (colorInput && colorInput.value.toLowerCase() !== sceneBackdropColor.toLowerCase()) {
            colorInput.value = sceneBackdropColor;
        }

        if (imageName) {
            imageName.textContent = sceneBackdropFileName || "تصویری انتخاب نشده است";
        }
        if (removeImage) removeImage.hidden = !sceneBackdropObjectUrl;
        if (uploadDropzone) {
            uploadDropzone.classList.remove("is-dragover");
            const subtitle = uploadDropzone.querySelector("small");
            if (subtitle) {
                subtitle.textContent = sceneBackdropFileName
                    ? "برای جایگزینی تصویر، فایل دیگری انتخاب کن یا اینجا رها کن."
                    : "تصویر PNG، JPG یا WEBP را انتخاب کن یا اینجا رها کن.";
            }
        }

        if (!sceneActive) renderSelectedPreview();
    }

    function setSceneBackdropMode(mode) {
        if (!["color", "image", "none"].includes(mode)) return;
        sceneBackdropMode = mode;
        applySceneBackdrop();
        syncSceneBackdropPanel();

        const statusNode = document.getElementById("studio-scene-status");
        if (!statusNode) return;

        if (mode === "color") {
            statusNode.textContent = "رنگ پس‌زمینه فوراً اعمال می‌شود؛ هیچ درخواستی به سرور ارسال نمی‌شود.";
        } else if (mode === "image") {
            statusNode.textContent = sceneBackdropObjectUrl
                ? "تصویر فقط به‌صورت محلی در همین صفحه نمایش داده می‌شود."
                : "یک تصویر انتخاب کن؛ فایل از دستگاهت خارج یا در دیتابیس ذخیره نمی‌شود.";
        } else {
            statusNode.textContent = "پس‌زمینه‌ای نمایش داده نمی‌شود؛ خروجی خود Canvas همچنان شفاف باقی می‌ماند.";
        }
    }

    async function loadSceneBackdropFile(file) {
        if (!file) return;

        const allowedType = /^image\/(png|jpeg|webp)$/i.test(file.type)
            || /\.(png|jpe?g|webp)$/i.test(file.name || "");
        const statusNode = document.getElementById("studio-scene-status");

        if (!allowedType) {
            if (statusNode) statusNode.textContent = "فرمت فایل باید PNG، JPG یا WEBP باشد.";
            return;
        }
        if (file.size > SCENE_BACKDROP_MAX_BYTES) {
            if (statusNode) statusNode.textContent = "حجم تصویر باید کمتر از ۱۵ مگابایت باشد.";
            return;
        }

        const token = ++sceneBackdropLoadToken;
        let nextUrl = URL.createObjectURL(file);

        try {
            // Decode locally before swapping the current backdrop to avoid flicker.
            const probe = new Image();
            await new Promise((resolve, reject) => {
                probe.onload = resolve;
                probe.onerror = () => reject(new Error("بارگذاری تصویر ممکن نشد."));
                probe.src = nextUrl;
            });

            // Large phone photos can decode to hundreds of megabytes. Downscale
            // them locally so the editor keeps a predictable memory footprint.
            const sourceWidth = probe.naturalWidth || probe.width;
            const sourceHeight = probe.naturalHeight || probe.height;
            const longestEdge = Math.max(sourceWidth, sourceHeight);
            const scale = longestEdge > 2560 ? 2560 / longestEdge : 1;

            if (scale < 1) {
                const resized = document.createElement("canvas");
                resized.width = Math.max(1, Math.round(sourceWidth * scale));
                resized.height = Math.max(1, Math.round(sourceHeight * scale));
                const context = resized.getContext("2d");
                if (!context) throw new Error("آماده‌سازی تصویر در مرورگر ممکن نشد.");

                context.drawImage(probe, 0, 0, resized.width, resized.height);
                const outputType = file.type === "image/png" ? "image/png" : "image/webp";
                const optimizedBlob = await new Promise((resolve, reject) => {
                    resized.toBlob(
                        blob => blob ? resolve(blob) : reject(new Error("فشرده‌سازی تصویر انجام نشد.")),
                        outputType,
                        0.88
                    );
                });

                const optimizedUrl = URL.createObjectURL(optimizedBlob);
                URL.revokeObjectURL(nextUrl);
                nextUrl = optimizedUrl;
            }

            if (token !== sceneBackdropLoadToken) {
                URL.revokeObjectURL(nextUrl);
                return;
            }

            if (sceneBackdropObjectUrl) URL.revokeObjectURL(sceneBackdropObjectUrl);
            sceneBackdropObjectUrl = nextUrl;
            sceneBackdropFileName = file.name || "backdrop-image";
            setSceneBackdropMode("image");
        } catch (error) {
            URL.revokeObjectURL(nextUrl);
            if (statusNode) statusNode.textContent = error.message || "خواندن تصویر انجام نشد.";
        }
    }

    function openSelectedPanel() {
        const workspace = root.closest(".customizer-workspace--premium") || root;
        workspace.dataset.studioPanelTab = "selected";
        syncSceneBackdropPanel();
    }

    function selectedLayerOrderTopFirst() {
        return Array.from(layers.values())
            .sort((a, b) => (Number(b.layer.z_index) || 0) - (Number(a.layer.z_index) || 0))
            .map(item => item.id);
    }

    function duplicateSelectedLayer() {
        const source = layers.get(selectedId);
        if (!source || source.layer.visible === false || source.layer.locked) return false;

        const base = normalizedGarmentPoint(source.surfacePoint || source.position) || {
            x: Number(source.layer.x ?? 0.5),
            y: Number(source.layer.y ?? 0.5),
        };
        const side = layerSide(source);
        const area = areaForSurfaceSide(side, areaById(source.layer.area_id, side));
        const offsets = [[0.055, 0.035], [-0.055, 0.035], [0, 0.07], [0, -0.07]];
        let hit = null;
        let nextX = base.x;
        let nextY = base.y;

        for (const [dx, dy] of offsets) {
            const candidateX = THREE.MathUtils.clamp(base.x + dx, 0.02, 0.98);
            const candidateY = THREE.MathUtils.clamp(base.y + dy, 0.02, 0.98);
            const candidateHit = garmentSurfaceHitAtPlacement(candidateX, candidateY, side);
            if (candidateHit && isValidPrintSurface(candidateHit, area)) {
                hit = candidateHit;
                nextX = candidateX;
                nextY = candidateY;
                break;
            }
        }

        if (!hit || !area) {
            status("فضای مناسبی برای تکثیر این لیبل پیدا نشد.");
            return false;
        }

        const newId = nextId++;
        const nextZ = layers.size
            ? Math.max(...Array.from(layers.values()).map(item => Number(item.layer.z_index) || 0)) + 1
            : 0;
        const layer = {
            ...source.layer,
            id: newId,
            x: nextX,
            y: nextY,
            area_id: area.id,
            z_index: nextZ,
            visible: true,
            locked: false,
        };
        const item = {
            id: newId,
            layer,
            artwork: { ...source.artwork },
            target: hit.object,
            position: hit.point.clone(),
            normal: hitNormal(hit),
            surfacePoint: hit.point.clone(),
            surfaceNormal: hitNormal(hit),
            projectRevision: 0,
            mesh: null,
            frame: null,
            handles: null,
            size: null,
        };

        layers.set(newId, item);
        selectedId = newId;
        openSelectedPanel();
        project(item, item.surfacePoint, item.surfaceNormal);
        sync();
        render();
        return true;
    }

    function moveLayerInStack(layerId, direction) {
        const ordered = selectedLayerOrderTopFirst();
        const index = ordered.indexOf(Number(layerId));
        if (index < 0) return;

        const nextIndex = index + (direction === "forward" ? -1 : 1);
        if (nextIndex < 0 || nextIndex >= ordered.length) return;

        [ordered[index], ordered[nextIndex]] = [ordered[nextIndex], ordered[index]];
        reorderLayers(ordered);
    }

    function bindSelectedPanelActions() {
        const actions = document.getElementById("studio-selected-actions");
        const scaleControls = document.querySelector(".studio-selected-scale-controls");
        if (!actions || actions.dataset.bound === "1") return;
        actions.dataset.bound = "1";

        actions.addEventListener("click", event => {
            const button = event.target.closest("[data-selected-action]");
            if (!button || button.disabled) return;

            const item = layers.get(selectedId);
            if (!item) return;
            const action = button.dataset.selectedAction;

            if (action === "duplicate") {
                duplicateSelectedLayer();
                return;
            }
            if (action === "delete") {
                removeLayerById(selectedId);
                return;
            }
            if (action === "bring-forward" || action === "send-back") {
                moveLayerInStack(selectedId, action === "bring-forward" ? "forward" : "back");
                return;
            }
            if (item.layer.locked) {
                status("این لایه قفل است؛ برای تغییر آن ابتدا قفل را باز کن.");
                return;
            }
            if (action === "scale-up" || action === "scale-down") {
                const factor = action === "scale-up" ? 1.1 : 0.9;
                const previousWidth = item.layer.width;
                const previousHeight = item.layer.height;
                item.layer.width = THREE.MathUtils.clamp(Number(previousWidth || 0.35) * factor, 0.06, 0.98);
                item.layer.height = THREE.MathUtils.clamp(Number(previousHeight || 0.25) * factor, 0.04, 0.78);
                const validation = validateLayerPlacement(item, placementForLayer(item));
                if (!validation.ok) {
                    item.layer.width = previousWidth;
                    item.layer.height = previousHeight;
                    status(validation.message);
                } else {
                    project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
                }
                sync();
                render();
                return;
            }
            if (action === "flip-x") item.layer.flip_x = !item.layer.flip_x;
            else if (action === "flip-y") item.layer.flip_y = !item.layer.flip_y;
            else return;

            project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
            sync();
            render();
            render2DPreview();
        });

        if (scaleControls && scaleControls.dataset.bound !== "1") {
            scaleControls.dataset.bound = "1";
            scaleControls.addEventListener("click", event => {
                const button = event.target.closest("[data-selected-action]");
                if (!button || button.disabled) return;

                const item = layers.get(selectedId);
                if (!item) return;
                if (item.layer.locked) {
                    status("این لایه قفل است؛ برای تغییر آن ابتدا قفل را باز کن.");
                    return;
                }

                const factor = button.dataset.selectedAction === "scale-up" ? 1.1 : 0.9;
                const previousWidth = item.layer.width;
                const previousHeight = item.layer.height;
                item.layer.width = THREE.MathUtils.clamp(Number(previousWidth || 0.35) * factor, 0.06, 0.98);
                item.layer.height = THREE.MathUtils.clamp(Number(previousHeight || 0.25) * factor, 0.04, 0.78);

                const validation = validateLayerPlacement(item, placementForLayer(item));
                if (!validation.ok) {
                    item.layer.width = previousWidth;
                    item.layer.height = previousHeight;
                    status(validation.message);
                } else {
                    project(item, item.surfacePoint || item.position, item.surfaceNormal || item.normal);
                }
                sync();
                render();
            });
        }
    }

    function bindSceneBackdropPanel() {
        const workspace = root.closest(".customizer-workspace--premium") || root;
        const tabs = document.querySelectorAll("[data-studio-panel-tab]");
        const scenePanel = document.getElementById("studio-scene-panel");
        if (!tabs.length || !scenePanel) return;

        workspace.dataset.studioPanelTab = "selected";
        tabs.forEach(button => {
            button.addEventListener("click", () => {
                workspace.dataset.studioPanelTab = button.dataset.studioPanelTab || "selected";
                syncSceneBackdropPanel();
            });
        });

        document.querySelectorAll("[data-scene-backdrop-mode]").forEach(button => {
            button.addEventListener("click", () => {
                setSceneBackdropMode(button.dataset.sceneBackdropMode);
            });
        });

        document.querySelectorAll("[data-scene-color]").forEach(button => {
            button.addEventListener("click", () => {
                const color = String(button.dataset.sceneColor || "").trim();
                if (!/^#[0-9a-f]{6}$/i.test(color)) return;
                sceneBackdropColor = color.toLowerCase();
                setSceneBackdropMode("color");
            });
        });

        document.getElementById("studio-scene-color-input")?.addEventListener("input", event => {
            const color = String(event.currentTarget.value || "").trim();
            if (!/^#[0-9a-f]{6}$/i.test(color)) return;
            sceneBackdropColor = color.toLowerCase();
            setSceneBackdropMode("color");
        });

        const fileInput = document.getElementById("studio-scene-image-input");
        fileInput?.addEventListener("change", event => {
            const file = event.currentTarget.files?.[0];
            if (file) void loadSceneBackdropFile(file);
            event.currentTarget.value = "";
        });

        const dropzone = document.getElementById("studio-scene-upload-dropzone");
        if (dropzone) {
            ["dragenter", "dragover"].forEach(type => {
                dropzone.addEventListener(type, event => {
                    event.preventDefault();
                    event.stopPropagation();
                    dropzone.classList.add("is-dragover");
                });
            });
            ["dragleave", "dragend"].forEach(type => {
                dropzone.addEventListener(type, event => {
                    event.preventDefault();
                    event.stopPropagation();
                    dropzone.classList.remove("is-dragover");
                });
            });
            dropzone.addEventListener("drop", event => {
                event.preventDefault();
                event.stopPropagation();
                dropzone.classList.remove("is-dragover");
                const file = Array.from(event.dataTransfer?.files || [])
                    .find(item => /^image\/(png|jpeg|webp)$/i.test(item.type) || /\.(png|jpe?g|webp)$/i.test(item.name || ""));
                if (file) void loadSceneBackdropFile(file);
            });
        }

        document.getElementById("studio-scene-image-remove")?.addEventListener("click", () => {
            sceneBackdropLoadToken += 1;
            if (sceneBackdropObjectUrl) URL.revokeObjectURL(sceneBackdropObjectUrl);
            sceneBackdropObjectUrl = null;
            sceneBackdropFileName = "";
            if (fileInput) fileInput.value = "";
            setSceneBackdropMode("none");
        });

        applySceneBackdrop();
        syncSceneBackdropPanel();
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
            const visibleGarmentHits = garmentHits(event);

            const handleHits = raycaster.intersectObjects(
                Array.from(layers.values()).map(item => item.handles).filter(Boolean),
                true
            );
            const handleHit = handleHits.find(hit => hit.object?.userData?.customizerHandleType);
            if (handleHit) {
                const layerId = Number(handleHit.object.userData.customizerLayerId);
                const selectedLayer = layers.get(layerId);
                selectedId = layerId;
                openSelectedPanel();
                drag = beginLayerTransform(
                    event,
                    selectedLayer,
                    handleHit.object.userData.customizerHandleType === "rotate" ? "rotate" : "resize",
                    handleHit.object.userData.customizerHandleType
                );
                if (drag) {
                    controls.enabled = false;
                    canvas.style.touchAction = "none";
                    canvas.setPointerCapture(event.pointerId);
                }
                sync();
                return;
            }

            const nearestGarmentDistance = visibleGarmentHits[0]?.distance ?? Infinity;
            const decal = raycaster.intersectObjects(
                Array.from(layers.values()).map(item => item.mesh).filter(Boolean),
                true
            ).find(hit =>
                hit.object?.userData?.customizerLayerId != null &&
                hit.distance <= nearestGarmentDistance + 0.025
            );

            if (decal) {
                selectedId = Number(decal.object.userData.customizerLayerId);
                openSelectedPanel();
                const selectedLayer = layers.get(selectedId);
                if (selectedLayer && !selectedLayer.layer.locked && selectedLayer.layer.visible !== false) {
                    const selectedArea = areaById(selectedLayer.layer.area_id, layerSide(selectedLayer));
                    const startSurfaceHit = visibleGarmentHits.find(hit =>
                        is3DPrintableArea(areaForSurfaceSide(surfaceSide(hitNormal(hit)), selectedArea)) &&
                        isValidPrintSurface(
                            hit,
                            areaForSurfaceSide(surfaceSide(hitNormal(hit)), selectedArea)
                        )
                    );
                    if (!startSurfaceHit) return;
                    drag = beginLayerTransform(event, selectedLayer, "move");
                    if (!drag) return;
                    drag.startPointerPoint = startSurfaceHit.point.clone();
                    drag.startSurfacePoint = startSurfaceHit.point.clone();
                    drag.startSurfaceNormal = hitNormal(startSurfaceHit);
                    drag.lastValidPoint = startSurfaceHit.point.clone();
                    drag.lastValidNormal = hitNormal(startSurfaceHit);
                    drag.lastValidTarget = startSurfaceHit.object;
                    controls.enabled = false;
                    canvas.style.touchAction = "none";
                    canvas.setPointerCapture(event.pointerId);
                } else {
                    drag = null;
                }
                sync();
                return;
            }

            if (event.button === 1 || event.altKey) return;

            const selectedLayer = layers.get(selectedId);
            if (selectedLayer && !selectedLayer.layer.locked && selectedLayer.layer.visible !== false) {
                const fallbackArea = areaById(selectedLayer.layer.area_id, layerSide(selectedLayer));
                const printableSurfaceHit = visibleGarmentHits.find(hit => {
                    const candidateArea = areaForSurfaceSide(surfaceSide(hitNormal(hit)), fallbackArea);
                    return is3DPrintableArea(candidateArea) && isValidPrintSurface(hit, candidateArea);
                });

                if (printableSurfaceHit) {
                    drag = beginLayerTransform(event, selectedLayer, "move");
                    if (drag) {
                        controls.enabled = false;
                        canvas.style.touchAction = "none";
                        canvas.setPointerCapture(event.pointerId);
                        sync();
                        return;
                    }
                }
            }

            // A blank click does not move a label. A real pointer movement is
            // required; once it starts, previewLayerMove projects onto the live surface hit.
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
                    applyLayerTransform(latestEvent);
                }
            });
        });

        ["pointerup", "pointercancel", "lostpointercapture"].forEach(type => {
            canvas.addEventListener(type, event => {
                if (drag?.pointerId !== event.pointerId) return;
                // Apply the last coalesced pointer position before ending the drag.
                if (pendingDragEvent?.pointerId === event.pointerId) {
                    applyLayerTransform(pendingDragEvent);
                }
                pendingDragEvent = null;
                if (dragFrameId) {
                    cancelAnimationFrame(dragFrameId);
                    dragFrameId = 0;
                }
                const completedDrag = drag;
                finishLayerTransform(completedDrag, event, type === "pointerup");
                drag = null;
                controls.enabled = true;
                canvas.style.touchAction = "";
                canvas.releasePointerCapture?.(event.pointerId);
                sync();
            });
        });

        document.querySelectorAll("[data-action]").forEach(button => {
            button.addEventListener("click", () => {
                const item = layers.get(selectedId);
                if (!item) return;

                const action = button.dataset.action;
                if (item.layer.locked && action !== "delete") {
                    status("این لایه قفل است؛ برای تغییر آن ابتدا قفل را باز کن.");
                    return;
                }

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
                    removeLayerById(selectedId);
                    return;
                }

                sync();
                render();
            });
        });

        document.querySelectorAll("[data-studio-view]").forEach(button => {
            button.addEventListener("click", () => setStudioView(button.dataset.studioView));
        });
        document.querySelectorAll("[data-2d-side]").forEach(button => {
            button.addEventListener("click", () => {
                active2DSide = button.dataset.twoDSide;
                document.querySelectorAll("[data-2d-side]").forEach(item => {
                    const active = item === button;
                    item.classList.toggle("is-active", active);
                    item.setAttribute("aria-pressed", String(active));
                });
                render2DPreview();
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
            if (item.layer.locked) {
                event.target.value = String(Math.round(item.layer.width * 100));
                status("این لایه قفل است؛ برای تغییر اندازه ابتدا قفل را باز کن.");
                return;
            }

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
            if (item.layer.locked) {
                event.target.value = String(Math.round(item.layer.rotation));
                status("این لایه قفل است؛ برای چرخاندن ابتدا قفل را باز کن.");
                return;
            }

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
                    preview_mode: `3d_glb_${garmentType}`,
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
        bindSceneBackdropPanel();
        bindSelectedPanelActions();
        bindSelectedPreviewInteraction();
        renderLayersPanel();
        renderSelectedPreview();
        resize();

        try {
            await loadGarment();
            setColor(currentVariant?.hex || "#ffffff");
            sync();
            updateGarmentPicker("tshirt", false);
            setStudioView(preferredStudioView);
        } catch (error) {
            console.error("GLB customizer model failed to load", error);
            setLoading("بارگذاری مدل سه‌بعدی انجام نشد.", true);
            status("مدل سه‌بعدی تیشرت بارگذاری نشد. مسیر GLB یا دسترسی فایل را بررسی کنید.");
            updateGarmentPicker("tshirt", false);
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
        if (sceneBackdropObjectUrl) {
            URL.revokeObjectURL(sceneBackdropObjectUrl);
            sceneBackdropObjectUrl = null;
        }
    }, { once: true });

    window.BabaeiCustomizer3D = {
        getPayload: saveLayers,
        isReady: () => Boolean(garment && garmentMeshes.length),
        setMode: setStudioView,
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