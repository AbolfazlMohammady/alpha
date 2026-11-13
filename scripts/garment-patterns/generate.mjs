import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { Teagan } from "@freesewing/teagan";
import { Hugo } from "@freesewing/hugo";
import { Brian } from "@freesewing/brian";
import { corePlugins } from "@freesewing/core-plugins";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, "../..");
const OUTPUT_DIR = path.join(
    PROJECT_ROOT,
    "config",
    "static",
    "customizer",
    "patterns"
);
const MEASUREMENTS_FILE = path.join(SCRIPT_DIR, "measurements.json");

function assertFinitePositive(value, label) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
        throw new Error(`Invalid measurement "${label}": expected a positive number.`);
    }
    return number;
}

function translationFromAttributes(attributes, label) {
    const transformValues = attributes?.getAsArray?.("transform") || [];
    const transformText = transformValues.join(" ");
    const unsupported = transformText.replace(
        /translate\(\s*-?[\d.]+(?:px)?[ ,]+\s*-?[\d.]+(?:px)?\s*\)/g,
        ""
    ).trim();

    if (unsupported) {
        throw new Error(
            `Unsupported transform on ${label}: "${transformText}". ` +
            "The pattern manifest only accepts translation-only packed layouts."
        );
    }

    let x = 0;
    let y = 0;
    const regex = /translate\(\s*(-?[\d.]+)(?:px)?[ ,]+\s*(-?[\d.]+)(?:px)?\s*\)/g;
    for (const match of transformText.matchAll(regex)) {
        x += Number(match[1]);
        y += Number(match[2]);
    }
    return { x, y };
}

function getPartBounds(part, stack) {
    const stackOffset = translationFromAttributes(stack.attributes, `stack ${stack.name}`);
    const partOffset = translationFromAttributes(part.attributes, `part ${part.name}`);
    const offsetX = stackOffset.x + partOffset.x;
    const offsetY = stackOffset.y + partOffset.y;

    const fabricPaths = Object.values(part.paths || {}).filter(pathObject => {
        if (pathObject.hidden) return false;
        const className = String(pathObject.attributes?.get?.("class") || "");
        return className.split(/\s+/).includes("fabric");
    });

    // Some designs contain helper/trim parts without a separate fabric
    // outline. Skip those; the required front/back body pieces are validated
    // explicitly after collecting all visible cut-piece bounds.
    if (!fabricPaths.length) return null;

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;

    for (const pathObject of fabricPaths) {
        if (!pathObject.topLeft || !pathObject.bottomRight) {
            pathObject.__boundary();
        }
        const left = Number(pathObject.topLeft?.x);
        const top = Number(pathObject.topLeft?.y);
        const right = Number(pathObject.bottomRight?.x);
        const bottom = Number(pathObject.bottomRight?.y);

        if (![left, top, right, bottom].every(Number.isFinite)) continue;
        minX = Math.min(minX, left + offsetX);
        minY = Math.min(minY, top + offsetY);
        maxX = Math.max(maxX, right + offsetX);
        maxY = Math.max(maxY, bottom + offsetY);
    }

    if (![minX, minY, maxX, maxY].every(Number.isFinite) || maxX <= minX || maxY <= minY) {
        return null;
    }

    return {
        x: minX,
        y: minY,
        width: maxX - minX,
        height: maxY - minY
    };
}

function collectPartBounds(pattern) {
    const result = {};
    for (const stack of Object.values(pattern.stacks || {})) {
        for (const part of stack.getPartList()) {
            const bounds = getPartBounds(part, stack);
            if (bounds) result[part.name] = bounds;
        }
    }
    return result;
}

function geometryForPiece(bounds, pageWidth, pageHeight, side) {
    // Keep a comfortable margin inside the actual front/back cut piece.
    // This rectangle is a suggested print zone, not a production cutting line.
    const inset = side === "front"
        ? { left: 0.20, top: 0.20, right: 0.80, bottom: 0.58 }
        : { left: 0.20, top: 0.18, right: 0.80, bottom: 0.62 };

    const left = bounds.x + bounds.width * inset.left;
    const top = bounds.y + bounds.height * inset.top;
    const right = bounds.x + bounds.width * inset.right;
    const bottom = bounds.y + bounds.height * inset.bottom;

    return [
        { x: Number((left / pageWidth).toFixed(6)), y: Number((top / pageHeight).toFixed(6)) },
        { x: Number((right / pageWidth).toFixed(6)), y: Number((top / pageHeight).toFixed(6)) },
        { x: Number((right / pageWidth).toFixed(6)), y: Number((bottom / pageHeight).toFixed(6)) },
        { x: Number((left / pageWidth).toFixed(6)), y: Number((bottom / pageHeight).toFixed(6)) }
    ];
}

function inspectPatternErrors(pattern, name) {
    const logs = pattern.getLogs();
    const errors = (logs.sets || []).flatMap(set => set?.error || set?.errors || []);
    if (errors.length) {
        const messages = errors.map(entry => typeof entry === "string" ? entry : JSON.stringify(entry));
        throw new Error(`${name} pattern drafting failed:\n${messages.join("\n")}`);
    }
}

function generateOne({ key, name, Design, options, partNames }, profile) {
    const settings = {
        units: profile.units || "metric",
        measurements: profile.measurements,
        options,
        sa: profile.seamAllowance,
        margin: profile.margin,
        layout: true,
        complete: true,
        paperless: false,
        locale: "en"
    };

    const pattern = new Design(settings);
    pattern.use(corePlugins);
    pattern.draft();
    inspectPatternErrors(pattern, key);

    const svg = pattern.render();
    if (typeof svg !== "string" || !svg.includes("<svg") || !/viewBox=/.test(svg)) {
        throw new Error(`FreeSewing did not produce a valid SVG for ${key}.`);
    }

    const pageWidth = assertFinitePositive(pattern.width, `${key}.pageWidth`);
    const pageHeight = assertFinitePositive(pattern.height, `${key}.pageHeight`);
    const bounds = collectPartBounds(pattern);

    const front = bounds[partNames.front];
    const back = bounds[partNames.back];
    if (!front || !back) {
        throw new Error(
            `Missing front/back pattern piece for ${key}. Found: ${Object.keys(bounds).join(", ")}`
        );
    }

    return {
        key,
        name,
        svg,
        page: { width: pageWidth, height: pageHeight },
        pieces: bounds,
        views: {
            front: {
                piece: partNames.front,
                pieceBounds: front,
                geometry: geometryForPiece(front, pageWidth, pageHeight, "front")
            },
            back: {
                piece: partNames.back,
                pieceBounds: back,
                geometry: geometryForPiece(back, pageWidth, pageHeight, "back")
            }
        }
    };
}

async function main() {
    const profile = JSON.parse(await fs.readFile(MEASUREMENTS_FILE, "utf8"));
    for (const [name, value] of Object.entries(profile.measurements || {})) {
        profile.measurements[name] = assertFinitePositive(value, name);
    }
    profile.seamAllowance = assertFinitePositive(profile.seamAllowance, "seamAllowance");
    profile.margin = assertFinitePositive(profile.margin, "margin");

    await fs.mkdir(OUTPUT_DIR, { recursive: true });

    const definitions = [
        {
            key: "tshirt",
            name: "Teagan T-shirt",
            Design: Teagan,
            options: { sleeveLength: 0.30 },
            partNames: { front: "teagan.front", back: "teagan.back" }
        },
        {
            key: "long_sleeve",
            name: "Brian Long Sleeve Block",
            Design: Brian,
            options: { sleeveLengthBonus: 0 },
            partNames: { front: "brian.front", back: "brian.back" }
        },
        {
            key: "hoodie",
            name: "Hugo Hoodie",
            Design: Hugo,
            options: {},
            partNames: { front: "hugo.front", back: "hugo.back" }
        }
    ];

    const manifest = {
        schemaVersion: 1,
        generated: true,
        generator: "FreeSewing v4",
        license: "MIT",
        measurementProfile: profile.measurements,
        seamAllowanceMm: profile.seamAllowance,
        models: {}
    };

    for (const definition of definitions) {
        console.log(`Generating ${definition.name}...`);
        const generated = generateOne(definition, profile);
        const fileName = `${definition.key}.svg`;
        await fs.writeFile(path.join(OUTPUT_DIR, fileName), generated.svg, "utf8");

        manifest.models[definition.key] = {
            name: generated.name,
            svg: fileName,
            page: generated.page,
            views: generated.views,
            pieces: Object.fromEntries(
                Object.entries(generated.pieces).map(([partName, bounds]) => [
                    partName,
                    {
                        x: Number(bounds.x.toFixed(2)),
                        y: Number(bounds.y.toFixed(2)),
                        width: Number(bounds.width.toFixed(2)),
                        height: Number(bounds.height.toFixed(2))
                    }
                ])
            )
        };
        console.log(
            `  ✓ ${fileName} (${generated.page.width.toFixed(1)} × ${generated.page.height.toFixed(1)} mm)`
        );
    }

    const manifestPath = path.join(OUTPUT_DIR, "manifest.json");
    await fs.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");

    console.log("\nDone. Generated pattern files:");
    for (const definition of definitions) {
        console.log(`  - config/static/customizer/patterns/${definition.key}.svg`);
    }
    console.log("  - config/static/customizer/patterns/manifest.json");
}

main().catch(error => {
    console.error("\nPattern generation failed:");
    console.error(error?.stack || error);
    process.exitCode = 1;
});
