"""Assemble the intro video: title cards and app footage into one MP4.

    uv run --no-project --with imageio-ffmpeg python compose.py

imageio-ffmpeg brings a complete ffmpeg (libx264, xfade) without installing
anything system-wide; the one Playwright ships encodes nothing but VP8.

App clips were captured as a screencast: frames arrive only when the page
repaints, each with the time it was drawn. So a clip is rebuilt as a list of
frames with *durations* and resampled to a constant 30fps — real timing,
preserved. The one exception is the stretch spent waiting on the models,
which record.mjs marks and shows a "sped up" badge for; only that stretch
is compressed.
"""

import bisect
import json
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
HERE = Path(__file__).resolve().parent
WORK = HERE / ".work"
OUT = HERE / "out"
FPS = 30
CROSSFADE = 0.6

# Inside the wait on the models, each pipeline step is shown at real speed for
# READ seconds — long enough to read its caption — and the dead time between
# steps is squeezed to GAP. A uniform speed-up cannot do this: a 4-minute run
# squeezed evenly into 8 seconds flashes each caption for a tenth of a second.
READ = 2.4
GAP = 0.35
# Extra time on the caption showing when the wait begins, which otherwise
# gets barely a second before the first compressed gap.
HOLD = 0.8

SEQUENCE = [
    ("card", "hook"),
    ("card", "title"),
    ("clip", "research"),
    ("card", "graph"),
    ("clip", "learn"),
    ("card", "proof"),
    ("card", "outro"),
]

ENCODE = ["-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(FPS)]

# Frames are JPEGs: full-range BT.601. Players, browsers and LinkedIn assume
# limited-range BT.709 for HD video, and reading one as the other crushes the
# blacks of a dark UI and shifts its accent colour. Convert once, and say so.
TO_VIDEO_RANGE = "scale=in_range=pc:out_range=tv:in_color_matrix=bt601:out_color_matrix=bt709,format=yuv420p"
# The filter graph's frame properties override the encoder's flags, so the
# final frames are stamped directly as well.
SETPARAMS = "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"
TAGS = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def run(*args: str) -> None:
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def duration(path: Path) -> float:
    probe = subprocess.run([FFMPEG, "-i", str(path)], capture_output=True, text=True).stderr
    stamp = probe.split("Duration: ")[1].split(",")[0]
    hours, minutes, seconds = stamp.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def retime(meta: dict):
    """Map real capture time onto video time, compressing the marked wait.

    Returns the mapping and how many times faster the wait plays overall.
    Built as piecewise-linear knots (real time, video time): 1x before the
    wait, READ-second windows at 1x from each beat, GAP for everything else.
    """
    marks = meta.get("marks", {})
    fast = marks.get("fast")
    if not fast or len(fast) < 2:
        return (lambda t: t), None
    start, end = fast[0], fast[1]
    beats = sorted(b for b in marks.get("beats", []) if start < b < end)

    knots = [(start, start + HOLD)]
    real, video = start, start + HOLD
    for beat in beats:
        keep_from, keep_to = max(beat, real), min(beat + READ, end)
        if keep_from > real:
            video += min(keep_from - real, GAP)
            real = keep_from
            knots.append((real, video))
        if keep_to > real:
            video += keep_to - real
            real = keep_to
            knots.append((real, video))
    if end > real:
        video += min(end - real, GAP)
        knots.append((end, video))
    shift = video - end

    def mapped(t: float) -> float:
        if t <= start:
            return t
        if t >= end:
            return t + shift
        for (r0, v0), (r1, v1) in zip(knots, knots[1:], strict=False):
            if r0 <= t <= r1:
                return v0 + (t - r0) * (v1 - v0) / (r1 - r0)
        return t + shift

    return mapped, (end - start) / (video - start)


def encode_clip(name: str) -> Path:
    folder = WORK / "clips" / name
    meta = json.loads((folder / "frames.json").read_text())
    # Frames can arrive a frame or two out of order. Their timestamps say when
    # they were drawn, which is the order that matters; arrival order made
    # negative gaps that, clamped to zero, stretched a 33s clip to 37s.
    frames = sorted(meta["frames"], key=lambda frame: frame["t"])
    mapped, factor = retime(meta)

    # Resample here rather than handing ffmpeg a duration per captured frame:
    # inside a compressed gap thousands of frames last microseconds each, and
    # any floor on those durations adds up to seconds. For each output frame,
    # take the latest captured frame drawn by then; a run of the same frame
    # becomes one entry lasting a whole number of output frames.
    times = [mapped(frame["t"]) for frame in frames]
    base, last = times[0], mapped(meta["ended"])
    picks = []
    for index in range(round((last - base) * FPS)):
        chosen = max(0, bisect.bisect_right(times, base + index / FPS) - 1)
        if picks and picks[-1][0] == chosen:
            picks[-1][1] += 1
        else:
            picks.append([chosen, 1])

    lines = []
    for chosen, count in picks:
        lines.append(f"file '{folder / frames[chosen]['file']}'")
        lines.append(f"duration {count / FPS:.6f}")
    # The concat demuxer ignores the last duration unless the file repeats.
    lines.append(f"file '{folder / frames[picks[-1][0]]['file']}'")
    listing = WORK / f"{name}.concat"
    listing.write_text("\n".join(lines) + "\n")

    out = WORK / f"seg_{name}.mp4"
    source = ["-f", "concat", "-safe", "0", "-i", str(listing)]
    run(*source, "-vf", f"fps={FPS},{TO_VIDEO_RANGE}", *ENCODE, *TAGS, str(out))
    real = meta["ended"] - frames[0]["t"]
    note = f", wait sped up {factor:.1f}x" if factor else ""
    print(f"  {name}: {real:.1f}s captured -> {duration(out):.1f}s{note}")
    return out


def encode_card(name: str) -> Path:
    out = WORK / f"seg_{name}.mp4"
    source = ["-framerate", str(FPS), "-i", str(WORK / "cards" / name / "%06d.jpg")]
    run(*source, "-vf", TO_VIDEO_RANGE, *ENCODE, *TAGS, str(out))
    print(f"  {name}: {duration(out):.1f}s")
    return out


def main() -> None:
    OUT.mkdir(exist_ok=True)
    print("segments")
    segments = [encode_card(name) if kind == "card" else encode_clip(name) for kind, name in SEQUENCE]
    lengths = [duration(segment) for segment in segments]

    # One crossfade between each pair; each offset is where the next segment
    # starts fading in, measured on the output timeline built so far.
    inputs, chain, offset, previous = [], [], 0.0, "0:v"
    for index, segment in enumerate(segments):
        inputs += ["-i", str(segment)]
        if index == 0:
            offset = lengths[0]
            continue
        offset -= CROSSFADE
        label = f"v{index}"
        chain.append(f"[{previous}][{index}:v]xfade=transition=fade:duration={CROSSFADE}:offset={offset:.3f}[{label}]")
        offset += lengths[index]
        previous = label
    total = offset
    fades = f"fade=t=in:st=0:d=0.5,fade=t=out:st={total - 0.9:.3f}:d=0.9"
    chain.append(f"[{previous}]{fades},format=yuv420p,{SETPARAMS}[out]")

    final = OUT / "dossier-intro.mp4"
    run(
        *inputs,
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[out]",
        *ENCODE,
        *TAGS,
        "-profile:v",
        "high",
        "-movflags",
        "+faststart",
        str(final),
    )

    # A poster frame for wherever the video is embedded: the title card, fully in.
    run("-ss", "4.2", "-i", str(WORK / "seg_title.mp4"), "-frames:v", "1", str(OUT / "dossier-intro-poster.jpg"))

    size = final.stat().st_size / 1_000_000
    print(f"\n{final.relative_to(HERE.parent)}  {duration(final):.1f}s  {size:.1f} MB")


if __name__ == "__main__":
    main()
