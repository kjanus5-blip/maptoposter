#!/usr/bin/env node
/* Czyta podpisy ze zdjęcia tablicy i składa gotową talię dla Ślepej Tablicy.
   Wymaga: npm install tesseract.js

   node ocr-deck.mjs tablica.jpg > talia.json
   node ocr-deck.mjs tablica.jpg --name "Serce — przekrój" --lang pol+eng --min-conf 45 > talia.json

   Powstały plik wczytuje się w aplikacji przyciskiem „Wczytaj talię”.
   OCR zawsze warto sprawdzić w zakładce Opisz — ramki bywają celniejsze niż odczytany tekst. */
import { readFileSync } from "node:fs";
import { basename, extname } from "node:path";
import { createWorker } from "tesseract.js";

const args = process.argv.slice(2);
const flags = {}; const rest = [];
for (let i = 0; i < args.length; i++){
  if (args[i].startsWith("--")) flags[args[i].slice(2)] = args[++i];
  else rest.push(args[i]);
}
const flag = (n, d) => flags[n] ?? d;
const img = rest[0];
if (!img){
  console.error("użycie: node ocr-deck.mjs tablica.jpg [--name nazwa] [--lang pol] [--min-conf 50] > talia.json");
  process.exit(1);
}
const mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[extname(img).toLowerCase()];
if (!mime){ console.error("obsługuję .jpg, .png i .webp"); process.exit(1); }
const minConf = +flag("min-conf", 50);

/* Słowa sklejamy w podpisy po odstępach: dwie etykiety na jednej linii
   (typowe dla tablic) muszą trafić do osobnych ramek. */
function runs(data){
  const lines = [];
  if (Array.isArray(data.lines) && data.lines.length) lines.push(...data.lines);
  else for (const b of data.blocks || []) for (const p of b.paragraphs || []) lines.push(...(p.lines || []));
  const grow = (a, b) => ({x0: Math.min(a.x0, b.x0), y0: Math.min(a.y0, b.y0), x1: Math.max(a.x1, b.x1), y1: Math.max(a.y1, b.y1)});
  const out = [];
  for (const line of lines){
    const words = (line.words || []).filter(w => w.text?.trim());
    if (!words.length){
      if (line.bbox && line.text?.trim()) out.push({text: line.text.trim(), bbox: line.bbox, conf: line.confidence});
      continue;
    }
    const h = Math.max(6, line.bbox.y1 - line.bbox.y0);
    let cur = null;
    for (const w of words){
      if (cur && w.bbox.x0 - cur.bbox.x1 < h * 1.6){
        cur.text += " " + w.text.trim(); cur.bbox = grow(cur.bbox, w.bbox); cur.conf = Math.min(cur.conf, w.confidence);
      } else { if (cur) out.push(cur); cur = {text: w.text.trim(), bbox: {...w.bbox}, conf: w.confidence}; }
    }
    if (cur) out.push(cur);
  }
  return out;
}

const worker = await createWorker(flag("lang", "pol"), 1, {
  logger: m => process.stderr.write(`\r${m.status} ${Math.round(m.progress * 100)}%   `),
});
const {data} = await worker.recognize(img, {}, {blocks: true, text: true});
await worker.terminate();
process.stderr.write("\n");

const bytes = readFileSync(img);
const {W, H} = imageSize(bytes);
if (!W || !H){ console.error("nie odczytałem wymiarów obrazu — przerywam"); process.exit(1); }

/** Wymiary z nagłówka pliku — bez dodatkowych bibliotek. */
function imageSize(b){
  if (b[0] === 0x89 && b[1] === 0x50) return {W: b.readUInt32BE(16), H: b.readUInt32BE(20)};      // PNG
  if (b[0] === 0xff && b[1] === 0xd8){                                                            // JPEG
    let i = 2;
    while (i < b.length){
      if (b[i] !== 0xff) { i++; continue; }
      const m = b[i + 1];
      if (m >= 0xc0 && m <= 0xcf && m !== 0xc4 && m !== 0xc8 && m !== 0xcc) return {W: b.readUInt16BE(i + 7), H: b.readUInt16BE(i + 5)};
      i += 2 + b.readUInt16BE(i + 2);
    }
  }
  if (b.slice(0, 4).toString() === "RIFF" && b.slice(8, 12).toString() === "WEBP"){                // WebP (VP8X/VP8L/VP8)
    const t = b.slice(12, 16).toString();
    if (t === "VP8X") return {W: (b.readUIntLE(24, 3) & 0xffffff) + 1, H: (b.readUIntLE(27, 3) & 0xffffff) + 1};
    if (t === "VP8 ") return {W: b.readUInt16LE(26) & 0x3fff, H: b.readUInt16LE(28) & 0x3fff};
  }
  return {W: 0, H: 0};
}

const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
const cards = [];
for (const r of runs(data)){
  const text = r.text.replace(/\s+/g, " ").replace(/^[^\p{L}(]+|[^\p{L})]+$/gu, "").trim();
  if (r.conf < minConf || text.length < 4 || !/\p{L}{3}/u.test(text)) continue;
  const box = {x: r.bbox.x0 / W, y: r.bbox.y0 / H, w: (r.bbox.x1 - r.bbox.x0) / W, h: (r.bbox.y1 - r.bbox.y0) / H};
  if (box.w > 0.6 || box.h > 0.2 || box.w < 0.01) continue;         // tytuł albo śmieć, nie podpis
  cards.push({id: uid(), box, pin: {x: box.x + box.w / 2, y: box.y + box.h / 2},
              name: text, note: "", srs: {box: 1, due: 0, seen: 0, ok: 0, streak: 0, lastMs: 0}});
}
const deck = {
  id: uid(), name: flag("name", basename(img, extname(img)).replace(/[_-]+/g, " ")),
  created: Date.now(), updated: Date.now(), maskStyle: "solid", thumb: "",
  image: `data:${mime};base64,${bytes.toString("base64")}`, cards,
};
process.stdout.write(JSON.stringify({app: "slepa-tablica", version: 1, deck}));
console.error(`talia „${deck.name}”: ${cards.length} podpisów`);
for (const c of cards) console.error("  ·", c.name);
