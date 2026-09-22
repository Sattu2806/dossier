# Intro video

A 1:48 walkthrough, 1080p, built from the **real app** — a live research run and
a real study guide — between title cards in the app's own design language.

```
hook → title → research (live) → how it works → learn a book → proof → outro
```

## Re-recording

```bash
cd video && npm install
npm --prefix ../web run build && cp -R ../web/.next/static ../web/.next/standalone/.next/

node record.mjs --rehearse   # slow fakes, zero quota: check the choreography first
node record.mjs              # the real take: one research run (~4-10 model calls)
node cards.mjs               # title cards
npm run build                # → out/dossier-intro.mp4 and a poster frame
```

`record.mjs` starts its own API and web server and stops them afterwards. The
API runs on a **copy** of `data/dossier.db` (see `serve.py`): recording needs a
known API key, keys are stored hashed one per user, and seeding one into your
real database would replace yours.

## How it is made, and the parts that were not obvious

**App footage is a DevTools screencast**, not screenshots in a loop. Frames
arrive when the page repaints, each stamped with when it was drawn, so
`compose.py` rebuilds real timing at a constant 30fps.

- The screencast ignores an *emulated* device pixel ratio and returns 1280×720.
  `--force-device-scale-factor=1.5` gets true 1920×1080.
- Frames arrive slightly out of order (125 times in a 34-second clip). They are
  sorted by draw time; in arrival order the negative gaps stretched 33s to 37s.
- Frames are chosen per output frame rather than listed with durations. Inside a
  compressed stretch thousands of frames last microseconds each, and any floor on
  those durations added up to 11 seconds.

**The wait on the models is sped up, and says so.** A badge is on screen for
exactly the stretch that is compressed. Each pipeline step keeps 2.4 seconds at
real speed so its caption can be read; the dead time between steps is squeezed.
A uniform speed-up cannot do this — the recorded run took 4m20s because Gemini
was returning 503s, and squeezing that evenly flashes each caption for a tenth
of a second.

**Captions follow the app's own progress timeline**, waiting for each step's row
to appear. The first version searched the whole page, and "Researching" is also
what the submit button says the moment you click it — so that caption fired 30
seconds early.

**Title cards are rendered on a virtual clock.** Every CSS animation is paused
and seeked to each frame's time before capture, so the cards are perfectly
smooth however slow the machine is.

**Colour.** Frames are full-range BT.601 JPEGs; players assume limited-range
BT.709 for HD video and reading one as the other crushes the blacks of a dark UI.
`compose.py` converts and tags the output.

**No audio track.** Captions carry it, since most feeds autoplay muted; add
music in any editor.
