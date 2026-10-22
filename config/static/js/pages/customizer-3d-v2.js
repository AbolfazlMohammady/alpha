import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { DecalGeometry } from "three/addons/geometries/DecalGeometry.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

(() => {
    "use strict";

    const root = document.getElementById("customizer");
    const stage = document.getElementById("designer-3d-stage");
    const canvas = document.getElementById("designer-3d-canvas");
    const loading = document.getElementById("designer-3d-loading");
    if (!root || !stage || !canvas) return;

    let data = {};
    try {
        data = JSON.parse(document.getElementById("designer-data")?.textContent || "{}");
    } catch (error) {
        console.error("Customizer 3D data is invalid", error);
        return;
    }

    const views = data.views || [];
    const artworks = data.artworks || [];
    const variants = data.variants || [];
    const prices = data.prices || {};
    const basePrice = Number(data.base_price || 0);
    const modelViews = views.filter((view) => view.model);
    if (!modelViews.length) return;

    const modelMeshes = [];
    const layers = new Map();
    const textureCache = new Map();
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const bounds = new THREE.Box3();
    const center = new THREE.Vector3();
    const size = new THREE.Vector3();
    const zAxis = new THREE.Vector3(0, 0, 1);

    let scene;
    let camera;
    let renderer;
    let controls;
    let modelRoot;
    let pmrem;
    let environment;
    let selectedLayerId = null;
    let activeAreaId = null;
    let nextLayerId = 1;
    let dragState = null;
    let currentVariant = null;
    let modelRotationY = 0;
    let modelRadius = 1.6;

    const artworkById = (id) => artworks.find((item) => Number(item.id) === Number(id));

    function setStatus(text) {
        const el = document.getElementById("save-status");
        if (el) el.textContent = text || "";
    }

    function csrfToken() {
        const match = document.cookie.split(";").map((x) => x.trim()).find((x) => x.startsWith("csrftoken="));
        return match ? decodeURIComponent(match.slice(10)) : "";
    }

    function render() {
        if (renderer && scene && camera) renderer.render(scene, camera);
    }

    function resize() {
        if (!renderer || !camera) return;
        const width = Math.max(1, stage.clientWidth);
        const height = Math.max(1, stage.clientHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        render();
    }

    function setupEnvironment() {
        pmrem = new THREE.PMREMGenerator(renderer);
        environment = new RoomEnvironment();
        scene.environment = pmrem.fromScene(environment, 0.04).texture;
        scene.environmentIntensity = 0.8;
        environment.dispose();
        environment = null;
    }

    function fitCamera(object) {
        bounds.setFromObject(object);
        bounds.getCenter(center);
        bounds.getSize(size);
        const maxDimension = Math.max(size.x, size.y, size.z) || 1;
        const scale = 2.9 / maxDimension;
        object.scale.multiplyScalar(scale);
        object.updateMatrixWorld(true);

        bounds.setFromObject(object);
        bounds.getCenter(center);
        bounds.getSize(size);
        object.position.sub(center);
        object.updateMatrixWorld(true);

        bounds.setFromObject(object);
        bounds.getCenter(center);
        bounds.getSize(size);
        const maxSize = Math.max(size.x, size.y, size.z) || 1;
        modelRadius = maxSize * 0.5;

        const fov = THREE.MathUtils.degToRad(camera.fov);
        const distance = (maxSize * 0.62) / Math.tan(fov / 2);
        camera.position.set(0, maxSize * 0.035, Math.max(3.1, distance * 1.12));
        camera.near = Math.max(0.01, maxSize / 100);
        camera.far = Math.max(50, maxSize * 20);
        camera.lookAt(0, 0, 0);
        controls?.target.set(0, 0, 0);
        controls?.minDistance = Math.max(1.1, maxSize * 0.65);
        controls?.maxDistance = Math.max(7, maxSize * 4.5);
        camera.updateProjectionMatrix();
    }

    function cloneMaterial(material) {
        if (!material) return material;
        const cloned = material.clone();
        if ("envMapIntensity" in cloned) cloned.envMapIntensity = 1.35;
        if ("roughness" in cloned) cloned.roughness = Math.min(0.92, Math.max(0.48, Number(cloned.roughness ?? 0.72)));
        if ("metalness" in cloned) cloned.metalness = Math.min(0.08, Math.max(0, Number(cloned.metalness ?? 0)));
        if (cloned.color && cloned.color.getHSL({}).l < 0.08) {
            cloned.emissive = new THREE.Color(0x161616);
            cloned.emissiveIntensity = 0.22;
        }
        return cloned;
    }

    function setupModel(object) {
        modelMeshes.length = 0;
        object.traverse((node) => {
            if (!node.isMesh) return;
            node.castShadow = true;
            node.receiveShadow = true;
            node.frustumCulled = false;
            if (Array.isArray(node.material)) node.material = node.material.map(cloneMaterial);
            else node.material = cloneMaterial(node.material);
            modelMeshes.push(node);
        });
        if (!modelMeshes.length) throw new Error("GLB بارگذاری شد اما هیچ Mesh قابل نمایشی داخل آن نیست.");
        applyVariantColor();
    }

    function applyVariantColor() {
        if (!modelRoot || !currentVariant?.hex) return;
        const color = new THREE.Color(currentVariant.hex);
        modelRoot.traverse((node) => {
            if (!node.isMesh) return;
            const materials = Array.isArray(node.material) ? node.material : [node.material];
            materials.forEach((material) => {
                if (!material?.color) return;
                const textured = Boolean(material.map || material.normalMap || material.roughnessMap);
                if (textured) material.color.lerp(color, 0.12);
                else material.color.lerp(color, 0.08);
                material.needsUpdate = true;
            });
        });
        render();
    }

    function loadTexture(url) {
        if (textureCache.has(url)) return textureCache.get(url);
        const loader = new THREE.TextureLoader();
        loader.setCrossOrigin("anonymous");
        const promise = loader.loadAsync(url).then((texture) => {
            texture.colorSpace = THREE.SRGBColorSpace;
            texture.anisotropy = renderer?.capabilities.getMaxAnisotropy?.() || 1;
            return texture;
        });
        textureCache.set(url, promise);
        return promise;
    }

    function eventPointer(event) {
        const rect = canvas.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
        pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    }

    function hits(event, includeDecals = false) {
        eventPointer(event);
        raycaster.setFromCamera(pointer, camera);
        const targets = includeDecals
            ? [modelRoot, ...Array.from(layers.values()).map((item) => item.mesh).filter(Boolean)]
            : modelMeshes;
        return raycaster.intersectObjects(targets, true);
    }

    function centerHit() {
        raycaster.setFromCamera(new THREE.Vector2(0, 0), camera);
        return raycaster.intersectObjects(modelMeshes, true)[0] || null;
    }

    function hitNormal(hit) {
        return (hit.face?.normal?.clone() || new THREE.Vector3(0, 0, 1))
            .transformDirection(hit.object.matrixWorld)
            .normalize();
    }

    function orientationFor(normal, rotation = 0) {
        const n = normal.clone().normalize();
        const align = new THREE.Quaternion().setFromUnitVectors(zAxis, n);
        const spin = new THREE.Quaternion().setFromAxisAngle(n, THREE.MathUtils.degToRad(rotation));
        return new THREE.Euler().setFromQuaternion(spin.multiply(align));
    }

    function activeArea() {
        if (activeAreaId) {
            for (const view of views) {
                const area = (view.areas || []).find((item) => Number(item.id) === Number(activeAreaId));
                if (area) return area;
            }
        }
        return modelViews[0]?.areas?.[0] || views[0]?.areas?.[0] || null;
    }

    function disposeLayer(item) {
        if (!item?.mesh) return;
        item.mesh.geometry?.dispose();
        item.mesh.material?.dispose();
        scene.remove(item.mesh);
        item.mesh = null;
    }

    function project(item, point, normal) {
        if (!item?.artwork?.image) return;
        loadTexture(item.artwork.image).then((texture) => {
            if (!layers.has(item.id)) return;
            disposeLayer(item);
            item.position = point.clone();
            item.normal = normal.clone().normalize();
            const aspect = Math.max(0.1, (texture.image?.width || 1) / Math.max(1, texture.image?.height || 1));
            const width = Math.max(0.035, modelRadius * 0.55 * Number(item.layer.width || 0.35) / 0.35);
            const decalSize = new THREE.Vector3(width, width / aspect, Math.max(0.006, width * 0.025));
            item.size = decalSize;
            const target = item.targetMesh || modelMeshes[0];
            if (!target) return;
            const geometry = new DecalGeometry(target, item.position, orientationFor(item.normal, item.layer.rotation), decalSize);
            const material = new THREE.MeshStandardMaterial({
                map: texture,
                transparent: true,
                alphaTest: 0.025,
                roughness: 0.6,
                metalness: 0,
                depthTest: true,
                depthWrite: false,
                polygonOffset: true,
                polygonOffsetFactor: -6,
                polygonOffsetUnits: -2,
                side: THREE.DoubleSide,
            });
            material.emissive = new THREE.Color(item.id === selectedLayerId ? 0x332712 : 0x000000);
            material.emissiveIntensity = item.id === selectedLayerId ? 0.14 : 0;
            const mesh = new THREE.Mesh(geometry, material);
            mesh.renderOrder = 30 + Number(item.layer.z_index || 0);
            mesh.userData.customizerLayerId = item.id;
            scene.add(mesh);
            item.mesh = mesh;
            render();
        }).catch((error) => {
            console.error("Artwork texture failed", error);
            setStatus("تصویر لیبل برای پیش‌نمایش سه‌بعدی بارگذاری نشد.");
        });
    }

    function addLayer(artworkId) {
        const artwork = artworkById(artworkId);
        const hit = centerHit();
        const area = activeArea();
        if (!artwork || !hit || !area) return;
        const count = Array.from(layers.values()).filter((item) => Number(item.layer.area_id) === Number(area.id)).length;
        const maxLayers = Number(area.max_layers || 3);
        if (count >= maxLayers) {
            setStatus(`در «${area.name}» بیشتر از ${maxLayers} لیبل مجاز نیست.`);
            return;
        }
        const layer = { id: nextLayerId++, artwork_id: artwork.id, area_id: area.id, x: 0.5, y: 0.5, width: 0.35, height: 0.25, rotation: 0, z_index: layers.size };
        const item = { id: layer.id, layer, artwork, targetMesh: hit.object, position: hit.point.clone(), normal: hitNormal(hit), mesh: null, size: null };
        layers.set(item.id, item);
        selectedLayerId = item.id;
        activeAreaId = area.id;
        project(item, item.position, item.normal);
        syncUi();
    }

    function selectLayer(id) {
        selectedLayerId = id == null ? null : Number(id);
        layers.forEach((item) => {
            const material = item.mesh?.material;
            if (!material) return;
            const selected = item.id === selectedLayerId;
            material.emissive?.setHex(selected ? 0x332712 : 0x000000);
            material.emissiveIntensity = selected ? 0.14 : 0;
        });
        syncUi();
        render();
    }

    function moveSelected(event) {
        const item = layers.get(selectedLayerId);
        if (!item) return false;
        const hit = hits(event)[0];
        if (!hit) return false;
        item.targetMesh = hit.object;
        project(item, hit.point, hitNormal(hit));
        return true;
    }

    function savePayload() {
        return Array.from(layers.values()).map((item) => ({
            ...item.layer,
            three_d: {
                position: item.position?.toArray().map((v) => Number(v.toFixed(6))) || null,
                normal: item.normal?.toArray().map((v) => Number(v.toFixed(6))) || null,
                mesh: item.targetMesh?.name || null,
                size: item.size?.toArray().map((v) => Number(v.toFixed(6))) || null,
                model_view_id: modelViews[0]?.id || null,
                mode: "surface_decal",
            },
        }));
    }

    function formatPrice(value) { return Number(value || 0).toLocaleString("fa-IR"); }

    function syncUi() {
        const selected = layers.get(selectedLayerId);
        const selectedCard = document.getElementById("selected-card");
        const controlsEl = document.getElementById("selected-controls");
        const premiumSelected = document.getElementById("premium-selected-artwork");
        if (selectedCard) selectedCard.innerHTML = selected
            ? `<div class="selected-card__title">${selected.artwork.name || "لیبل"}</div><span class="selected-card__meta">${activeArea()?.name || "ناحیه چاپ"} · ${Math.round(selected.layer.width * 100)}% × ${Math.round(selected.layer.height * 100)}%</span>`
            : '<span class="selected-card__empty">یک لیبل را انتخاب کنید.</span>';
        if (controlsEl) controlsEl.hidden = !selected;
        if (premiumSelected) premiumSelected.innerHTML = selected
            ? `<div class="premium-selected-artwork__name">لیبل انتخاب‌شده: <strong>${selected.artwork.name || "لیبل"}</strong></div><div class="premium-selected-artwork__hint">برای جابه‌جایی، مستقیماً روی لیبل بکش.</div>`
            : "";

        let total = currentVariant ? Number(currentVariant.price) : basePrice;
        const lines = [`<div class="price-line"><span>محصول</span><strong>${formatPrice(total)} تومان</strong></div>`];
        layers.forEach((item) => {
            const key = `${item.layer.artwork_id}:${item.layer.area_id}`;
            const price = Object.prototype.hasOwnProperty.call(prices, key) ? Number(prices[key]) : Number(item.artwork.base_price || 0);
            total += price;
            lines.push(`<div class="price-line"><span>${item.artwork.name || "لیبل"}</span><strong>+ ${formatPrice(price)}</strong></div>`);
        });
        const breakdown = document.getElementById("price-breakdown");
        const totalEl = document.getElementById("designer-total");
        if (breakdown) breakdown.innerHTML = lines.join("");
        if (totalEl) totalEl.textContent = formatPrice(total);
    }

    function renderVariantColors() {
        const host = document.getElementById("variant-color-list");
        if (!host) return;
        const seen = new Set();
        host.innerHTML = variants.filter((variant) => {
            if (seen.has(variant.color)) return false;
            seen.add(variant.color);
            return true;
        }).map((variant) => `<button type="button" class="premium-color-button" style="--swatch:${variant.hex || "#c9c4ba"}" data-variant-color="${variant.color}" title="${variant.color}" aria-label="${variant.color}"></button>`).join("");
        host.querySelectorAll(".premium-color-button").forEach((button) => button.addEventListener("click", () => {
            currentVariant = variants.find((item) => item.color === button.dataset.variantColor && Number(item.stock) > 0) || variants.find((item) => item.color === button.dataset.variantColor) || null;
            const select = document.getElementById("variant-select");
            if (select && currentVariant) select.value = String(currentVariant.id);
            host.querySelectorAll(".premium-color-button").forEach((item) => item.classList.toggle("is-active", item === button));
            applyVariantColor();
            syncUi();
        }));
    }

    function setMode(mode) {
        const is3d = mode === "3d";
        document.getElementById("designer-2d-stage")?.classList.toggle("is-hidden", is3d);
        document.getElementById("designer-3d-stage")?.classList.toggle("is-hidden", !is3d);
        document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("is-active", button.dataset.mode === mode));
        if (is3d) resize();
    }

    function bindInteractions() {
        canvas.addEventListener("pointerdown", (event) => {
            const intersections = hits(event, true);
            const decal = intersections.find((hit) => hit.object?.userData?.customizerLayerId != null);
            if (decal) {
                selectLayer(decal.object.userData.customizerLayerId);
                dragState = { pointerId: event.pointerId };
                controls.enabled = false;
                canvas.setPointerCapture(event.pointerId);
                return;
            }
            if (event.altKey || event.button === 1) return;
            if (selectedLayerId != null && moveSelected(event)) {
                dragState = { pointerId: event.pointerId };
                controls.enabled = false;
                canvas.setPointerCapture(event.pointerId);
            }
        });
        canvas.addEventListener("pointermove", (event) => { if (dragState?.pointerId === event.pointerId) moveSelected(event); });
        ["pointerup", "pointercancel"].forEach((type) => canvas.addEventListener(type, (event) => {
            if (dragState?.pointerId !== event.pointerId) return;
            dragState = null;
            controls.enabled = true;
            canvas.releasePointerCapture?.(event.pointerId);
            syncUi();
        }));

        document.getElementById("artwork-grid")?.addEventListener("click", (event) => {
            const card = event.target.closest(".artwork-card");
            if (card) window.setTimeout(() => addLayer(Number(card.dataset.artworkId)), 0);
        });
        document.getElementById("area-list")?.addEventListener("click", (event) => {
            const button = event.target.closest(".area-option");
            if (button) activeAreaId = Number(button.dataset.areaId);
        });
        document.querySelectorAll("[data-action]").forEach((button) => button.addEventListener("click", () => {
            const item = layers.get(selectedLayerId);
            if (!item) return;
            const action = button.dataset.action;
            if (action === "scale-up" || action === "scale-down") {
                const factor = action === "scale-up" ? 1.06 : 0.94;
                item.layer.width = Math.min(1, Math.max(0.02, item.layer.width * factor));
                item.layer.height = Math.min(1, Math.max(0.02, item.layer.height * factor));
                project(item, item.position, item.normal);
            } else if (action === "rotate-left" || action === "rotate-right") {
                item.layer.rotation = Math.max(-180, Math.min(180, item.layer.rotation + (action === "rotate-left" ? -5 : 5)));
                project(item, item.position, item.normal);
            } else if (action === "delete") {
                disposeLayer(item);
                layers.delete(selectedLayerId);
                selectedLayerId = null;
            }
            syncUi();
            render();
        }));
        document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => setMode(button.dataset.mode)));
        document.getElementById("variant-select")?.addEventListener("change", (event) => {
            currentVariant = variants.find((item) => String(item.id) === String(event.target.value)) || null;
            applyVariantColor();
            syncUi();
        });
        document.getElementById("view-switcher")?.addEventListener("click", () => {
            window.setTimeout(() => {
                const index = Number(document.querySelector("#view-switcher .view-button.is-active")?.dataset.viewIndex || 0);
                activeAreaId = views[index]?.areas?.[0]?.id || activeAreaId;
            }, 0);
        });
        document.getElementById("designer-3d-rotation")?.addEventListener("input", (event) => {
            modelRotationY = THREE.MathUtils.degToRad(Number(event.target.value));
            if (modelRoot) modelRoot.rotation.y = modelRotationY;
            render();
        });
        document.getElementById("designer-3d-reset")?.addEventListener("click", () => {
            modelRotationY = 0;
            if (modelRoot) modelRoot.rotation.y = 0;
            controls?.reset();
            const slider = document.getElementById("designer-3d-rotation");
            if (slider) slider.value = "0";
            render();
        });
        document.getElementById("save-design")?.addEventListener("click", async (event) => {
            event.preventDefault();
            event.stopImmediatePropagation();
            const button = event.currentTarget;
            button.disabled = true;
            setStatus("در حال بررسی و ذخیره طراحی سه‌بعدی…");
            try {
                const response = await fetch(root.dataset.saveUrl, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                    credentials: "same-origin",
                    body: JSON.stringify({ variant_id: document.getElementById("variant-select")?.value || null, version: 2, preview_mode: "3d_surface_decal", layers: savePayload() }),
                });
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "ذخیره طراحی انجام نشد.");
                setStatus(`طراحی سه‌بعدی ذخیره شد · کد ${String(result.draft_id).slice(0, 8)}`);
            } catch (error) {
                setStatus(error.message || "ذخیره طراحی انجام نشد.");
            } finally {
                button.disabled = false;
            }
        }, { capture: true });
    }

    function initScene() {
        scene = new THREE.Scene();
        scene.background = null;
        camera = new THREE.PerspectiveCamera(30, 1, 0.01, 100);
        camera.position.set(0, 0.15, 4.8);
        renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "high-performance" });
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.toneMapping = THREE.ACESFilmicToneMapping;
        renderer.toneMappingExposure = 1.18;
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFSoftShadowMap;
        setupEnvironment();

        controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.06;
        controls.enablePan = false;
        controls.rotateSpeed = 0.72;
        controls.zoomSpeed = 0.82;
        controls.minPolarAngle = 0.5;
        controls.maxPolarAngle = 2.65;
        controls.addEventListener("change", render);

        scene.add(new THREE.HemisphereLight(0xffffff, 0x333333, 1.65));
        const key = new THREE.DirectionalLight(0xffffff, 5.0);
        key.position.set(3.8, 5.5, 5.0);
        key.castShadow = true;
        key.shadow.mapSize.set(2048, 2048);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0xc9d7ff, 2.0);
        fill.position.set(-4, 2.5, 2);
        scene.add(fill);
        const rim = new THREE.DirectionalLight(0xffd9a6, 2.4);
        rim.position.set(2.5, 3.2, -4.5);
        scene.add(rim);
        scene.add(new THREE.PointLight(0xffffff, 1.2, 12));
        resize();
    }

    async function loadModel(view) {
        loading?.classList.remove("is-hidden");
        if (loading) loading.textContent = "در حال بارگذاری مدل واقعی محصول…";
        const loader = new GLTFLoader();
        loader.setCrossOrigin("anonymous");
        const draco = new DRACOLoader();
        draco.setDecoderPath("https://cdn.jsdelivr.net/npm/three@0.186.0/examples/jsm/libs/draco/");
        draco.setWorkerLimit(2);
        loader.setDRACOLoader(draco);
        let gltf;
        try {
            gltf = await loader.loadAsync(view.model);
        } finally {
            draco.dispose();
        }
        if (!gltf?.scene) throw new Error("فایل GLB معتبر است اما صحنه‌ای داخل آن پیدا نشد.");
        if (modelRoot) scene.remove(modelRoot);
        modelRoot = gltf.scene;
        fitCamera(modelRoot);
        setupModel(modelRoot);
        modelRoot.rotation.y = modelRotationY;
        scene.add(modelRoot);
        if (loading) loading.classList.add("is-hidden");
        setStatus("مدل سه‌بعدی آماده است.");
        render();
    }

    function showFailure(error) {
        console.error("Customizer 3D model load failed", error);
        if (loading) {
            loading.classList.remove("is-hidden");
            loading.textContent = "بارگذاری مدل سه‌بعدی ناموفق بود.";
        }
        setStatus(`خطای مدل سه‌بعدی: ${error?.message || "فایل GLB قابل نمایش نیست."}`);
    }

    function animate() {
        requestAnimationFrame(animate);
        controls?.update();
        renderer?.render(scene, camera);
    }

    renderVariantColors();
    currentVariant = variants.find((item) => Number(item.stock) > 0) || variants[0] || null;
    if (currentVariant) {
        const select = document.getElementById("variant-select");
        if (select && !select.value) select.value = String(currentVariant.id);
    }
    bindInteractions();
    initScene();
    loadModel(modelViews[0]).catch(showFailure);
    syncUi();
    animate();
    window.addEventListener("resize", resize);

    window.BabaeiCustomizer3D = {
        getPayload: savePayload,
        isReady: () => Boolean(modelRoot && modelMeshes.length),
        setMode,
        addArtwork: addLayer,
    };
})();
