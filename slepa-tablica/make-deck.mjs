#!/usr/bin/env node
/* Składa talię dla Ślepej Tablicy ze zdjęcia i listy podpisów.
   Użycie:  node make-deck.mjs tablica.jpg podpisy.json [nazwa talii] > talia.json
   Podpisy: [{"name": "...", "box": [x, y, w, h], "pin": [x, y], "note": "..."}]
            współrzędne względne (0–1) względem lewego górnego rogu zdjęcia. */
import { readFileSync } from "node:fs";
import { basename, extname } from "node:path";

const [img, labels, title] = process.argv.slice(2);
if (!img || !labels){
  console.error("użycie: node make-deck.mjs tablica.jpg podpisy.json [nazwa talii] > talia.json");
  process.exit(1);
}
const mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}[extname(img).toLowerCase()];
if (!mime) { console.error("obsługuję .jpg, .png i .webp"); process.exit(1); }

const uid = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);
const list = JSON.parse(readFileSync(labels, "utf8"));
const cards = list.map(l => {
  const [x, y, w, h] = l.box;
  if ([x, y, w, h].some(v => typeof v !== "number" || v < 0 || v > 1)) throw new Error(`zła ramka przy „${l.name}”`);
  return {
    id: uid(),
    box: {x, y, w, h},
    pin: l.pin ? {x: l.pin[0], y: l.pin[1]} : {x: x + w / 2, y: y + h / 2},
    name: l.name, note: l.note || "",
    srs: {box: 1, due: 0, seen: 0, ok: 0, streak: 0, lastMs: 0},
  };
});
const deck = {
  id: uid(),
  name: title || basename(img, extname(img)).replace(/[_-]+/g, " "),
  created: Date.now(), updated: Date.now(),
  maskStyle: "solid", thumb: "",
  image: `data:${mime};base64,${readFileSync(img).toString("base64")}`,
  cards,
};
process.stdout.write(JSON.stringify({app: "slepa-tablica", version: 1, deck}));
console.error(`talia „${deck.name}”: ${cards.length} podpisów`);
