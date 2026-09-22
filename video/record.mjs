// Records the app segments of the intro video from the real, running app.
//
//   node record.mjs                  live: real searches, real Gemini quota (~5-10 calls)
//   node record.mjs --rehearse       slow fakes: rehearse the choreography for free
//   node record.mjs --only learn     one clip
//
// It starts its own API (on a copy of your database — see serve.py) and web
// server, drives real Chrome, and captures with the DevTools screencast.
// Screencast frames arrive only when something repaints, each stamped with
// the time it was drawn, so compose.py can rebuild real timing at a constant
// 30fps instead of trusting how fast screenshots happened to come back.
import puppeteer from "puppeteer-core";
import { spawn } from "node:child_process";
import { createWriteStream, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const WORK = join(HERE, ".work");
const argv = process.argv.slice(2);
const REHEARSE = argv.includes("--rehearse");
const ONLY = argv.includes("--only") ? argv[argv.indexOf("--only") + 1] : null;

const API = "http://127.0.0.1:8511";
const WEB = "http://127.0.0.1:3611";
const KEY = "dsr_video_local_recording_only";
// 1280x720 CSS pixels at 1.5x: the app is laid out at a laptop width, and
// every frame is still a full 1920x1080.
const VIEW = { width: 1280, height: 720, deviceScaleFactor: 1.5 };
const TOPIC = "Why aren't solid-state batteries in our phones yet?";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
mkdirSync(WORK, { recursive: true });

// --- servers ------------------------------------------------------------------

const children = [];

function start(name, command, args, env = {}) {
  const child = spawn(command, args, {
    cwd: ROOT,
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
    detached: true, // its own process group, so `uv run`'s python dies with it
  });
  const log = createWriteStream(join(WORK, `${name}.log`));
  child.stdout.pipe(log);
  child.stderr.pipe(log);
  children.push(child);
  return child;
}

function stopAll() {
  for (const child of children) {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
  }
}
process.on("exit", stopAll);
process.on("SIGINT", () => process.exit(130));

async function ready(url, timeout = 90_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.status < 500) return;
    } catch {}
    await sleep(400);
  }
  throw new Error(`${url} never came up — see video/.work/*.log`);
}

// --- what gets drawn on top of the app ------------------------------------------
//
// Headless Chrome draws no mouse pointer, so the video carries its own: it
// follows real mousemove events, which means hover states in the app fire
// exactly where the pointer is seen to be.

function overlay() {
  const install = () => {
    if (document.getElementById("__v_cursor")) return;
    const style = document.createElement("style");
    style.textContent = `
      html { scroll-behavior: smooth; }
      #__v_cursor { position: fixed; left: 0; top: 0; z-index: 2147483647; pointer-events: none;
        transform: translate(-80px, -80px); will-change: transform;
        filter: drop-shadow(0 3px 8px rgba(0,0,0,.55)); }
      #__v_ripple { position: fixed; z-index: 2147483646; pointer-events: none; width: 38px; height: 38px;
        margin: -19px 0 0 -19px; border-radius: 50%; border: 2px solid #5eead4; opacity: 0; }
      #__v_ripple.go { animation: __v_ripple .55s cubic-bezier(.2,.7,.3,1); }
      @keyframes __v_ripple { from { opacity: .95; transform: scale(.25); } to { opacity: 0; transform: scale(1.35); } }
      #__v_caption { position: fixed; left: 50%; bottom: 28px; z-index: 2147483645; pointer-events: none;
        transform: translate(-50%, 14px); opacity: 0; transition: opacity .4s ease, transform .4s cubic-bezier(.2,.7,.3,1);
        display: flex; align-items: center; gap: 14px; padding: 13px 22px 13px 18px; border-radius: 14px;
        background: rgba(7,8,10,.82); border: 1px solid rgba(255,255,255,.09);
        backdrop-filter: blur(16px) saturate(140%); -webkit-backdrop-filter: blur(16px) saturate(140%);
        box-shadow: 0 18px 50px -12px rgba(0,0,0,.8), 0 0 0 1px rgba(94,234,212,.06);
        font-family: var(--font-geist-sans), ui-sans-serif, system-ui; font-size: 19px; letter-spacing: -.012em;
        color: #edf1f7; white-space: nowrap; }
      #__v_caption.on { opacity: 1; transform: translate(-50%, 0); }
      #__v_caption .k { font-family: var(--font-geist-mono), ui-monospace, monospace; font-size: 11.5px;
        letter-spacing: .16em; text-transform: uppercase; color: #5eead4; padding-right: 14px;
        border-right: 1px solid rgba(255,255,255,.12); }
      #__v_caption .k:empty { display: none; }
      #__v_ff { position: fixed; top: 70px; right: 22px; z-index: 2147483645; pointer-events: none; opacity: 0;
        transition: opacity .3s ease; display: flex; align-items: center; gap: 7px; padding: 6px 11px;
        border-radius: 999px; background: rgba(7,8,10,.8); border: 1px solid rgba(94,234,212,.28);
        font-family: var(--font-geist-mono), ui-monospace, monospace; font-size: 10.5px; letter-spacing: .16em;
        text-transform: uppercase; color: #5eead4; }
      #__v_ff.on { opacity: 1; }
    `;
    document.head.appendChild(style);

    const cursor = document.createElement("div");
    cursor.id = "__v_cursor";
    cursor.innerHTML = `<svg width="24" height="30" viewBox="0 0 24 30"><path d="M2 2 L2 24 L8 18.5 L12.2 27.5 L16 25.8 L11.9 17 L20 17 Z"
      fill="#fff" stroke="#07080a" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
    const ripple = document.createElement("div");
    ripple.id = "__v_ripple";
    const caption = document.createElement("div");
    caption.id = "__v_caption";
    caption.innerHTML = `<span class="k"></span><span class="t"></span>`;
    const ff = document.createElement("div");
    ff.id = "__v_ff";
    ff.innerHTML = `<svg width="13" height="9" viewBox="0 0 13 9"><path d="M0 0 L6 4.5 L0 9Z M6.5 0 L12.5 4.5 L6.5 9Z" fill="#5eead4"/></svg>sped up`;
    document.body.append(caption, ff, ripple, cursor);

    const at = window.__v_at || { x: -80, y: -80 };
    cursor.style.transform = `translate(${at.x}px, ${at.y}px)`;
    document.addEventListener(
      "mousemove",
      (event) => {
        window.__v_at = { x: event.clientX, y: event.clientY };
        cursor.style.transform = `translate(${event.clientX - 2}px, ${event.clientY - 2}px)`;
      },
      true,
    );
    document.addEventListener(
      "mousedown",
      (event) => {
        ripple.style.left = `${event.clientX}px`;
        ripple.style.top = `${event.clientY}px`;
        ripple.classList.remove("go");
        void ripple.offsetWidth;
        ripple.classList.add("go");
      },
      true,
    );

    let swap = Promise.resolve();
    window.__v = {
      caption(text, kicker = "") {
        swap = swap.then(async () => {
          if (caption.classList.contains("on")) {
            caption.classList.remove("on");
            await new Promise((resolve) => setTimeout(resolve, 380));
          }
          caption.querySelector(".k").textContent = kicker;
          caption.querySelector(".t").textContent = text;
          if (text) caption.classList.add("on");
        });
        return swap;
      },
      fastForward(on) {
        ff.classList.toggle("on", on);
      },
      // Our own eased scroll: the browser's smooth scroll has no duration you
      // can choose, and a video needs one.
      scrollTo(y, ms) {
        const from = window.scrollY;
        const to = Math.max(0, Math.min(y, document.documentElement.scrollHeight - innerHeight));
        const began = performance.now();
        return new Promise((resolve) => {
          const step = (now) => {
            const t = Math.min(1, (now - began) / ms);
            const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
            window.scrollTo({ top: from + (to - from) * e, behavior: "instant" });
            if (t < 1) requestAnimationFrame(step);
            else resolve();
          };
          requestAnimationFrame(step);
        });
      },
    };
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install);
  else install();
}

// --- a person using the app -----------------------------------------------------

let pointer = { x: 1100, y: 640 };

async function moveTo(page, x, y, ms = 800) {
  const from = { ...pointer };
  const steps = Math.max(10, Math.round(ms / 16));
  // A slight arc: hands do not move in straight lines, and a ruler-straight
  // pointer is the first thing that makes a demo look automated.
  const bend = Math.min(60, Math.hypot(x - from.x, y - from.y) * 0.12);
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
    const lift = Math.sin(Math.PI * e) * bend;
    await page.mouse.move(from.x + (x - from.x) * e, from.y + (y - from.y) * e - lift);
    await sleep(14);
  }
  pointer = { x, y };
}

async function centre(page, selector) {
  const handle = await page.waitForSelector(selector, { visible: true, timeout: 20_000 });
  const box = await handle.boundingBox();
  return { x: box.x + box.width / 2, y: box.y + box.height / 2, handle };
}

async function hover(page, selector, ms) {
  const { x, y } = await centre(page, selector);
  await moveTo(page, x, y, ms);
}

async function click(page, selector, ms = 800) {
  await hover(page, selector, ms);
  await sleep(140);
  await page.mouse.down();
  await sleep(90);
  await page.mouse.up();
}

async function type(page, text) {
  for (const character of text) {
    await page.keyboard.type(character);
    // Faster inside words than between them, like a person.
    await sleep(character === " " ? 95 + Math.random() * 60 : 38 + Math.random() * 45);
  }
}

const caption = (page, text, kicker) => page.evaluate((t, k) => window.__v.caption(t, k), text, kicker ?? "");
const scrollTo = (page, y, ms = 1400) => page.evaluate((top, d) => window.__v.scrollTo(top, d), y, ms);
const scrollToElement = (page, selector, offset = 90, ms = 1400) =>
  page.evaluate(
    (s, o, d) => {
      const element = document.querySelector(s);
      return window.__v.scrollTo(element.getBoundingClientRect().top + window.scrollY - o, d);
    },
    selector,
    offset,
    ms,
  );

// Sections are found by the words a reader sees, not by class names that a
// restyle would change.
const mark = (page, text, name) =>
  page.evaluate(
    (t, n) => {
      const label = [...document.querySelectorAll("p")].find((p) => p.textContent.includes(t));
      label?.setAttribute("data-v", n);
    },
    text,
    name,
  );

// --- capture ------------------------------------------------------------------

// Moments compose.py needs to know about, stamped on the same clock as the
// frames. `fast` is the stretch spent waiting on the models: it is sped up in
// the edit, and the badge saying so is on screen for exactly that stretch.
let marks = {};
const now = () => Date.now() / 1000;

async function fastForward(page, on) {
  await page.evaluate((value) => window.__v.fastForward(value), on);
  (marks.fast ??= []).push(now());
}

async function capture(page, name, scene) {
  const dir = join(WORK, "clips", name);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });

  marks = {};
  const cdp = await page.createCDPSession();
  const frames = [];
  const writes = [];
  cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
    cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
    const file = `${String(frames.length).padStart(6, "0")}.jpg`;
    frames.push({ file, t: metadata.timestamp });
    writes.push(writeFile(join(dir, file), Buffer.from(data, "base64")));
  });

  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, maxWidth: 1920, maxHeight: 1080 });
  const began = Date.now() / 1000;
  console.log(`● recording ${name}`);
  await scene();
  const ended = Date.now() / 1000;
  await cdp.send("Page.stopScreencast");
  await Promise.all(writes);
  await cdp.detach();

  writeFileSync(join(dir, "frames.json"), JSON.stringify({ began, ended, marks, frames }));
  console.log(`■ ${name}: ${frames.length} frames over ${(ended - began).toFixed(1)}s`);
}

// --- the scenes -----------------------------------------------------------------

async function research(page) {
  await page.goto(`${WEB}/`, { waitUntil: "networkidle0" });
  await page.waitForSelector('input[placeholder="A topic, in plain words"]');
  await sleep(600);

  await capture(page, "research", async () => {
    await sleep(700);
    await caption(page, "Ask it anything worth researching.", "Research");
    await sleep(900);
    await click(page, 'input[placeholder="A topic, in plain words"]', 1000);
    await sleep(250);
    await type(page, TOPIC);
    await sleep(500);
    await click(page, 'button[type="submit"]', 650);

    // Captions follow the pipeline as it actually runs: each one waits for
    // the node it describes to appear in the app's own progress timeline.
    const beats = [
      ["Planning sub-questions", "A planner splits it into sub-questions."],
      ["Researching", "Researchers search the web — all in parallel."],
      ["Writing the draft", "A writer drafts from that evidence alone."],
      ["Fact-checking against sources", "A fact-checker tests every claim against its source."],
      ["Reviewing quality", "A critic scores the draft, and can send it back."],
    ];
    // Look only at the timeline's rows. The first version searched the whole
    // page, and "Researching" is also what the submit button says the moment
    // you click it — so that caption fired 30 seconds early.
    const reached = (label) =>
      page.waitForFunction(
        (l) => [...document.querySelectorAll("section ol li")].some((row) => row.textContent.includes(l)),
        { timeout: 300_000 },
        label,
      );
    // Every caption stays up long enough to read, even when the step it
    // describes finishes sooner. compose.py keeps READ seconds after each
    // stamped beat at real speed and compresses the rest.
    let shownAt = 0;
    const beat = async (text) => {
      await sleep(Math.max(0, shownAt + 2000 - Date.now()));
      (marks.beats ??= []).push(now());
      await caption(page, text, "Research");
      shownAt = Date.now();
    };

    await reached(beats[0][0]);
    await caption(page, beats[0][1], "Research");
    await sleep(1400);
    await fastForward(page, true);
    for (const [label, text] of beats.slice(1)) {
      await reached(label);
      await beat(text);
    }

    await page.waitForSelector(".report", { timeout: 240_000 });
    await fastForward(page, false);
    await sleep(600);
    await caption(page, "A report where every claim cites its source.", "Research");
    await scrollToElement(page, ".report", 84, 1700);
    await sleep(1300);
    await scrollTo(page, (await page.evaluate(() => scrollY)) + 240, 1900);
    await sleep(400);

    // Follow one citation to where it came from.
    const citation = await page.$(".report a.citation");
    if (citation) {
      await caption(page, "Click a citation to see exactly where it came from.", "Research");
      await citation.evaluate((element) => element.scrollIntoView({ block: "center", behavior: "instant" }));
      await sleep(300);
      await click(page, ".report a.citation", 900);
      await sleep(2100);
    }

    await caption(page, "Export it as Markdown, text, JSON or PDF.", "Research");
    // Bring the report's own header into view before reaching for it: the
    // pointer can only click what is on screen.
    await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((b) => b.textContent.trim() === "Export");
      button?.closest("div")?.setAttribute("data-v", "report-head");
    });
    await scrollToElement(page, "[data-v=report-head]", 150, 1500);
    await sleep(300);
    await click(page, "button::-p-text(Export)", 900);
    await sleep(1900);
    await page.keyboard.press("Escape");
    // Escape leaves a keyboard focus ring on the button; nobody watching
    // pressed a key, so it should not show.
    await page.evaluate(() => document.activeElement?.blur());
    await sleep(400);
    await click(page, "button::-p-text(Sources)", 800);
    // The sources list is shorter than the report it replaces, so the page
    // shrinks under the viewport; bring the tab back into frame.
    await scrollToElement(page, "[data-v=report-head]", 150, 700);
    await caption(page, "Only the sources it cited — none it made up.", "Research");
    await sleep(2300);
    await caption(page, "");
    await sleep(500);
  });
}

async function learn(page) {
  await page.goto(`${WEB}/learn`, { waitUntil: "networkidle0" });
  await sleep(600);

  await capture(page, "learn", async () => {
    await sleep(600);
    await caption(page, "Or give it a book — and be taught it.", "Learn");
    await sleep(700);
    await hover(page, "input[type=file] ~ *, [class*='border-dashed']", 1100).catch(() => {});
    await sleep(1400);
    await click(page, "a[href^='/guides/']", 1000);

    await page.waitForSelector("button::-p-text(Explain simply)", { timeout: 30_000 });
    await sleep(500);
    await moveTo(page, 1180, 560, 700);
    await caption(page, "Every lesson, explained like you're five…", "Learn");
    await sleep(3400);

    await click(page, "button::-p-text(The real thing)", 900);
    await caption(page, "…then properly, citing the page it came from.", "Learn");
    await sleep(3200);

    await caption(page, "Diagrams, drawn from the book.", "Learn");
    await mark(page, "How it fits together", "diagram");
    await scrollToElement(page, "[data-v=diagram]", 110, 1600);
    await sleep(2600);

    await caption(page, "Worked examples — syntax-checked, never executed.", "Learn");
    await mark(page, "Worked example", "example");
    await scrollToElement(page, "[data-v=example]", 120, 1400);
    await sleep(2800);

    await caption(page, "Then it checks you actually understood.", "Learn");
    await mark(page, "Check yourself", "check");
    await scrollToElement(page, "[data-v=check]", 140, 1300);
    await sleep(500);
    const question = await page.evaluateHandle(
      () => document.querySelector("[data-v=check]")?.nextElementSibling?.querySelector("button") ?? null,
    );
    if (question.asElement()) {
      await question.asElement().evaluate((element) => element.setAttribute("data-v", "question"));
      await click(page, "[data-v=question]", 900);
    }
    await sleep(2800);
    await caption(page, "");
    await sleep(500);
  });
}

// --- run ------------------------------------------------------------------------

const SCENES = { research, learn };

console.log(REHEARSE ? "rehearsal: slow fakes, no quota" : "LIVE: real searches and model calls");
start("api", "uv", ["run", "python", "video/serve.py"], REHEARSE ? { VIDEO_FAKE: "1" } : {});
start("web", "node", ["web/.next/standalone/server.js"], {
  DOSSIER_API_URL: API,
  PORT: "3611",
  HOSTNAME: "127.0.0.1",
});
await ready(`${API}/health`);
await ready(`${WEB}/`);

const browser = await puppeteer.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
  args: [
    `--window-size=${VIEW.width},${VIEW.height}`,
    // The screencast ignores an *emulated* pixel ratio and hands back
    // 1280x720; a real one gives full 1920x1080 frames.
    `--force-device-scale-factor=${VIEW.deviceScaleFactor}`,
    "--hide-scrollbars",
    "--force-color-profile=srgb",
  ],
  defaultViewport: VIEW,
});

try {
  const page = await browser.newPage();
  page.on("pageerror", (error) => console.log("[pageerror]", error.message));
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "dark" }]);
  await page.evaluateOnNewDocument(overlay);
  await browser.setCookie({
    name: "dossier_key",
    value: KEY,
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  });

  for (const [name, scene] of Object.entries(SCENES)) {
    if (!ONLY || ONLY === name) await scene(page);
  }
} finally {
  await browser.close();
  stopAll();
}
