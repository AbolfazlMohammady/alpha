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

const PATTERN_PREVIEW_STYLES = '<![CDATA[\n' +
    'svg { shape-rendering: geometricPrecision; }\n' +
    '.fabric:not(.sa) { fill: #fffefa; stroke: #292d35; stroke-width: 1.35; stroke-linecap: round; stroke-linejoin: round; }\n' +
    '.fabric.sa { fill: none; stroke: #b89a61; stroke-width: 1.05; stroke-dasharray: 6 4; stroke-linejoin: round; }\n' +
    'text:not(.pattern-piece-label), .text, .note, .help, .mark, .logo, .scalebox { display: none !important; }\n' +
    '.pattern-piece-label { display: block !important; fill: #77747b; font: 18px Arial, sans-serif; letter-spacing: .3px; }\n' +
    ']]>';

function stylePatternSvg(svg, key) {
    const styleStart = svg.indexOf('<style');
    const styleEnd = styleStart >= 0 ? svg.indexOf('</style>', styleStart) : -1;
    if (styleStart < 0 || styleEnd < 0) {
        throw new Error('FreeSewing SVG for ' + key + ' has no style block.');
    }
    const styleTag = '<style type="text/css">' + PATTERN_PREVIEW_STYLES + '</style>';
    return svg.slice(0, styleStart) + styleTag + svg.slice(styleEnd + '</style>'.length);
}


function extractStackGroup(svg, stackName) {
    const id = "fs-stack-" + stackName;
    const start = svg.indexOf('<g id="' + id + '"');
    if (start < 0) throw new Error("Missing FreeSewing stack group " + id);

    const openEnd = svg.indexOf(">", start);
    if (openEnd < 0) throw new Error("Malformed SVG group " + id);
    const openTag = svg.slice(start, openEnd + 1);
    const transform = (openTag.match(/\btransform="([^"]+)"/) || [])[1] || "";

    const tags = /<\/?g\b[^>]*>/g;
    tags.lastIndex = start;
    let depth = 0;
    let closeStart = -1;
    let match;
    while ((match = tags.exec(svg))) {
        depth += match[0].startsWith("</") ? -1 : 1;
        if (depth === 0) {
            closeStart = match.index;
            break;
        }
    }
    if (closeStart < 0) throw new Error("Unclosed FreeSewing stack group " + id);
    return { transform, inner: svg.slice(openEnd + 1, closeStart) };
}

function prefixSvgIds(fragment, prefix) {
    const ids = new Map();
    for (const match of fragment.matchAll(/\bid="([^"]+)"/g)) {
        if (!ids.has(match[1])) ids.set(match[1], prefix + "-" + match[1]);
    }
    let output = fragment.replace(/\bid="([^"]+)"/g, function(full, id) {
        return ids.has(id) ? 'id="' + ids.get(id) + '"' : full;
    });
    for (const entry of ids.entries()) {
        const oldId = entry[0];
        const newId = entry[1];
        output = output
            .split('href="#' + oldId + '"').join('href="#' + newId + '"')
            .split('xlink:href="#' + oldId + '"').join('xlink:href="#' + newId + '"')
            .split('url(#' + oldId + ')').join('url(#' + newId + ')');
    }
    return output;
}

function previewPrintGeometry(bounds, pageWidth, pageHeight, side) {
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

function buildPreviewLayout(args) {
    const svg = args.svg;
    const bounds = args.bounds;
    const frontName = args.frontName;
    const backName = args.backName;
    const sleeveName = args.sleeveName;
    const frontBounds = bounds[frontName];
    const backBounds = bounds[backName];
    const sleeveBounds = bounds[sleeveName];
    if (!frontBounds || !backBounds || !sleeveBounds) {
        throw new Error("The pattern preview needs front, back, and sleeve cut pieces.");
    }

    const stackNames = Array.from(svg.matchAll(/<g id="fs-stack-([^"]+)"/g)).map(function(match) {
        return match[1];
    });
    const groups = new Map(stackNames.map(function(name) {
        return [name, extractStackGroup(svg, name)];
    }));
    const frontGroup = groups.get(frontName);
    const backGroup = groups.get(backName);
    const sleeveGroup = groups.get(sleeveName);
    if (!frontGroup || !backGroup || !sleeveGroup) {
        throw new Error("Could not resolve the main FreeSewing pattern stacks.");
    }

    const margin = 36;
    const gap = 56;
    const frontWidth = frontBounds.width * 2;
    const backWidth = backBounds.width * 2;
    const pageWidth = margin * 2 + frontWidth + gap + backWidth;
    const bodyHeight = Math.max(frontBounds.height, backBounds.height);
    const frontPanel = {
        x: margin, y: margin + 34,
        width: frontWidth, height: frontBounds.height
    };
    const backPanel = {
        x: margin + frontWidth + gap, y: margin + 34,
        width: backWidth, height: backBounds.height
    };
    const elements = [];
    const labels = [];

    function addFullBody(name, group, pieceBounds, panel, label) {
        const centerX = panel.x + pieceBounds.width;
        const dy = panel.y - pieceBounds.y;
        const leftInner = prefixSvgIds(group.inner, name + "-left");
        const rightInner = prefixSvgIds(group.inner, name + "-right");

        // FreeSewing drafts each body piece on the fold. Reflect one half
        // about the min-X fold edge to display a complete symmetric panel.
        elements.push(
            '<g transform="translate(' + (centerX + pieceBounds.x) + ', ' + dy + ')">' +
            '<g transform="scale(-1, 1)"><g transform="' + group.transform + '">' +
            leftInner + '</g></g></g>'
        );
        elements.push(
            '<g transform="translate(' + (centerX - pieceBounds.x) + ', ' + dy + ')">' +
            '<g transform="' + group.transform + '">' + rightInner + '</g></g>'
        );
        labels.push(
            '<text class="pattern-piece-label" x="' + centerX + '" y="' + (margin + 20) +
            '" text-anchor="middle">' + label + '</text>'
        );
    }

    addFullBody(frontName, frontGroup, frontBounds, frontPanel, "Front");
    addFullBody(backName, backGroup, backBounds, backPanel, "Back");

    let cursorX = margin;
    let cursorY = margin + 34 + bodyHeight + gap;
    let rowHeight = 0;
    const placed = {};

    function placeMirrorPair(name, group, pieceBounds, label) {
        if (cursorX + pieceBounds.width * 2 + gap > pageWidth - margin + 0.01) {
            cursorY += rowHeight + gap;
            cursorX = margin;
            rowHeight = 0;
        }
        const x = cursorX;
        const y = cursorY;
        const leftInner = prefixSvgIds(group.inner, name + "-left");
        const rightInner = prefixSvgIds(group.inner, name + "-right");

        elements.push(
            '<g transform="translate(' + (x - pieceBounds.x) + ', ' + (y - pieceBounds.y) + ')">' +
            '<g transform="' + group.transform + '">' + leftInner + '</g></g>'
        );
        elements.push(
            '<g transform="translate(' + (x + pieceBounds.width * 2 + pieceBounds.x) +
            ', ' + (y - pieceBounds.y) + ')"><g transform="scale(-1, 1)">' +
            '<g transform="' + group.transform + '">' + rightInner + '</g></g></g>'
        );
        placed[name + ".left"] = {
            x: Number(x.toFixed(2)), y: Number(y.toFixed(2)),
            width: Number(pieceBounds.width.toFixed(2)), height: Number(pieceBounds.height.toFixed(2))
        };
        placed[name + ".right"] = {
            x: Number((x + pieceBounds.width).toFixed(2)), y: Number(y.toFixed(2)),
            width: Number(pieceBounds.width.toFixed(2)), height: Number(pieceBounds.height.toFixed(2))
        };
        labels.push(
            '<text class="pattern-piece-label" x="' + (x + pieceBounds.width) + '" y="' +
            (y + pieceBounds.height + 23) + '" text-anchor="middle">' + label + '</text>'
        );
        cursorX += pieceBounds.width * 2 + gap;
        rowHeight = Math.max(rowHeight, pieceBounds.height + 28);
    }

    function placeOne(name, group, pieceBounds) {
        if (cursorX + pieceBounds.width > pageWidth - margin + 0.01) {
            cursorY += rowHeight + gap;
            cursorX = margin;
            rowHeight = 0;
        }
        const x = cursorX;
        const y = cursorY;
        const inner = prefixSvgIds(group.inner, name + "-piece");
        elements.push(
            '<g transform="translate(' + (x - pieceBounds.x) + ', ' + (y - pieceBounds.y) + ')">' +
            '<g transform="' + group.transform + '">' + inner + '</g></g>'
        );
        placed[name] = {
            x: Number(x.toFixed(2)), y: Number(y.toFixed(2)),
            width: Number(pieceBounds.width.toFixed(2)), height: Number(pieceBounds.height.toFixed(2))
        };
        labels.push(
            '<text class="pattern-piece-label" x="' + (x + pieceBounds.width / 2) + '" y="' +
            (y + pieceBounds.height + 23) + '" text-anchor="middle">' +
            name.split(".").pop() + '</text>'
        );
        cursorX += pieceBounds.width + gap;
        rowHeight = Math.max(rowHeight, pieceBounds.height + 28);
    }

    placeMirrorPair(sleeveName, sleeveGroup, sleeveBounds, "Sleeves");
    const required = new Set([frontName, backName, sleeveName]);
    for (const name of stackNames) {
        if (required.has(name)) continue;
        const pieceBounds = bounds[name];
        const group = groups.get(name);
        if (pieceBounds && group) placeOne(name, group, pieceBounds);
    }

    const pageHeight = cursorY + rowHeight + margin;
    const defs = (svg.match(/<defs>[\s\S]*?<\/defs>/i) || [])[0] || "<defs></defs>";
    const styles = (svg.match(/<style[^>]*>[\s\S]*?<\/style>/i) || [])[0] || "";
    const previewSvg = [
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="' +
            pageWidth.toFixed(2) + 'mm" height="' + pageHeight.toFixed(2) + 'mm" viewBox="0 0 ' +
            pageWidth.toFixed(2) + ' ' + pageHeight.toFixed(2) + '">',
        styles,
        defs,
        '<g id="babaei-preview-layout">' + elements.join("\n") + labels.join("\n") + '</g>',
        "</svg>"
    ].join("\n");

    return {
        svg: previewSvg,
        page: { width: Number(pageWidth.toFixed(2)), height: Number(pageHeight.toFixed(2)) },
        pieces: {
            [frontName + ".full"]: {
                x: frontPanel.x, y: frontPanel.y,
                width: Number(frontPanel.width.toFixed(2)), height: Number(frontPanel.height.toFixed(2))
            },
            [backName + ".full"]: {
                x: backPanel.x, y: backPanel.y,
                width: Number(backPanel.width.toFixed(2)), height: Number(backPanel.height.toFixed(2))
            },
            ...placed
        },
        views: {
            front: {
                piece: frontName + ".full",
                pieceBounds: frontPanel,
                geometry: previewPrintGeometry(frontPanel, pageWidth, pageHeight, "front")
            },
            back: {
                piece: backName + ".full",
                pieceBounds: backPanel,
                geometry: previewPrintGeometry(backPanel, pageWidth, pageHeight, "back")
            }
        }
    };
}

function generateOne({ key, name, Design, options, partNames }, profile) {
    const settings = {
        units: profile.units || "metric",
        measurements: profile.measurements,
        options,
        sa: profile.seamAllowance,
        margin: profile.margin,
        layout: true,
        // Keep the SVG focused on pattern pieces, not the instruction sheet.
        complete: false,
        paperless: false,
        locale: "en"
    };

    const pattern = new Design(settings);
    pattern.use(corePlugins);
    pattern.draft();
    inspectPatternErrors(pattern, key);

    const rawSvg = pattern.render();
    if (typeof rawSvg !== "string" || !rawSvg.includes("<svg") || !/viewBox=/.test(rawSvg)) {
        throw new Error(`FreeSewing did not produce a valid SVG for ${key}.`);
    }

    const cutSvg = stylePatternSvg(rawSvg, key);
    const bounds = collectPartBounds(pattern);
    const preview = buildPreviewLayout({
        svg: cutSvg,
        bounds,
        frontName: partNames.front,
        backName: partNames.back,
        sleeveName: partNames.sleeve,
    });

    return {
        key,
        name,
        svg: preview.svg,
        cutSvg: rawSvg,
        page: preview.page,
        pieces: preview.pieces,
        views: preview.views,
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
            partNames: { front: "teagan.front", back: "teagan.back", sleeve: "teagan.sleeve" }
        },
        {
            key: "long_sleeve",
            name: "Brian Long Sleeve Block",
            Design: Brian,
            options: { sleeveLengthBonus: 0 },
            partNames: { front: "brian.front", back: "brian.back", sleeve: "library.sleeve" }
        },
        {
            key: "hoodie",
            name: "Hugo Hoodie",
            Design: Hugo,
            options: {},
            partNames: { front: "hugo.front", back: "hugo.back", sleeve: "hugo.sleeve" }
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
        const sourceFileName = `${definition.key}-freesewing.svg`;
        await fs.writeFile(path.join(OUTPUT_DIR, fileName), generated.svg, "utf8");
        await fs.writeFile(path.join(OUTPUT_DIR, sourceFileName), generated.cutSvg, "utf8");

        manifest.models[definition.key] = {
            name: generated.name,
            svg: fileName,
            sourceSvg: sourceFileName,
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
