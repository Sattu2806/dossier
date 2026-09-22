// Renders the title cards in cards.html to frames, on a virtual clock.
//
//   node cards.mjs            every scene
//   node cards.mjs graph      one scene
//
// Every animation is paused and then seeked to each frame's time before the
// screenshot, so a frame that takes 200ms to capture still lands exactly
// 1/30s after the last one. Real-time capture of the same page would stutter
// wherever the machine was busy.
import puppeteer from "puppeteer-core";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, ".work", "cards");
const FPS = 30;

// Seconds per scene. compose.py reads the frame count, not this table.
export const SCENES = { hook: 4.6, title: 4.8, graph: 10, proof: 6.5, outro: 5.6 };

const only = process.argv[2];
const browser = await puppeteer.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
  args: ["--window-size=1280,720", "--force-device-scale-factor=1.5", "--hide-scrollbars", "--force-color-profile=srgb"],
  defaultViewport: { width: 1280, height: 720, deviceScaleFactor: 1.5 },
});

try {
  const page = await browser.newPage();
  page.on("pageerror", (error) => console.log("[pageerror]", error.message));
  const base = pathToFileURL(join(HERE, "cards.html")).href;

  for (const [name, seconds] of Object.entries(SCENES)) {
    if (only && only !== name) continue;
    // A different query string forces a real navigation; a hash alone would
    // not re-run the page script that picks the scene.
    await page.goto(`${base}?${name}#${name}`, { waitUntil: "networkidle0" });
    await page.evaluate(async () => {
      await Promise.all([
        document.fonts.load('400 60px "Instrument Serif"'),
        document.fonts.load('italic 400 60px "Instrument Serif"'),
        document.fonts.load('400 16px "Geist"'),
        document.fonts.load('500 16px "Geist"'),
        document.fonts.load('400 12px "Geist Mono"'),
      ]);
      await document.fonts.ready;
      for (const animation of document.getAnimations()) animation.pause();
    });

    const dir = join(OUT, name);
    rmSync(dir, { recursive: true, force: true });
    mkdirSync(dir, { recursive: true });

    const frames = Math.round(seconds * FPS);
    for (let frame = 0; frame < frames; frame++) {
      await page.evaluate((t) => {
        for (const animation of document.getAnimations()) animation.currentTime = t * 1000;
        window.__tick(t);
      }, frame / FPS);
      const jpeg = await page.screenshot({ type: "jpeg", quality: 95 });
      writeFileSync(join(dir, `${String(frame).padStart(6, "0")}.jpg`), jpeg);
    }
    console.log(`■ ${name}: ${frames} frames`);
  }
} finally {
  await browser.close();
}
