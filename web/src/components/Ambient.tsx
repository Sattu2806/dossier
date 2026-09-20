"use client";

import { useEffect, useRef } from "react";

/**
 * The light behind the page: two slow-drifting colour fields plus a glow that
 * follows the pointer at a distance.
 *
 * Written with CSS custom properties driven from a rAF loop rather than React
 * state — a pointer move should never cause a render, and at 60Hz it would
 * cause a great many.
 */
export default function Ambient() {
  const layer = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    let frame = 0;
    let targetX = 50;
    let targetY = 0;
    let currentX = 50;
    let currentY = 0;

    function onMove(event: PointerEvent) {
      targetX = (event.clientX / window.innerWidth) * 100;
      targetY = (event.clientY / window.innerHeight) * 100;
    }

    function tick() {
      // Ease towards the pointer so the glow trails rather than snaps.
      currentX += (targetX - currentX) * 0.045;
      currentY += (targetY - currentY) * 0.045;
      layer.current?.style.setProperty("--px", `${currentX}%`);
      layer.current?.style.setProperty("--py", `${currentY}%`);
      frame = requestAnimationFrame(tick);
    }

    window.addEventListener("pointermove", onMove, { passive: true });
    frame = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <div ref={layer} aria-hidden className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Fixed fields: the composition, independent of the cursor. */}
      <div
        className="drift absolute -top-[30%] left-[8%] h-[70vh] w-[70vh] rounded-full opacity-[0.22] blur-[120px]"
        style={{ background: "radial-gradient(circle, var(--accent-deep), transparent 65%)" }}
      />
      <div
        className="drift-slow absolute -right-[10%] top-[18%] h-[55vh] w-[55vh] rounded-full opacity-[0.13] blur-[120px]"
        style={{ background: "radial-gradient(circle, var(--violet), transparent 65%)" }}
      />

      {/* The pointer glow. */}
      <div
        className="absolute inset-0 opacity-[0.55]"
        style={{
          background:
            "radial-gradient(420px circle at var(--px, 50%) var(--py, 0%), rgba(94,234,212,0.07), transparent 70%)",
        }}
      />

      {/* A faint ruled grid, masked so it fades before it becomes wallpaper. */}
      <div
        className="absolute inset-0 opacity-[0.16]"
        style={{
          backgroundImage:
            "linear-gradient(var(--line) 1px, transparent 1px), linear-gradient(90deg, var(--line) 1px, transparent 1px)",
          backgroundSize: "64px 64px",
          maskImage: "radial-gradient(120% 70% at 50% 0%, #000 20%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(120% 70% at 50% 0%, #000 20%, transparent 75%)",
        }}
      />
    </div>
  );
}
