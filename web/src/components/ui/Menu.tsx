"use client";

import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

export type MenuItem = { label: string; hint?: string; icon?: React.ReactNode; onSelect: () => void };

/** A dropdown that closes on outside click, on Escape, and after a choice —
 *  the three ways people expect to get out of one. */
export default function Menu({ trigger, items }: { trigger: React.ReactNode; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    function onPointerDown(event: MouseEvent) {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={container} className="relative">
      <button
        onClick={() => setOpen((previous) => !previous)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-[13px] text-muted transition-colors hover:border-accent/40 hover:text-text"
      >
        {trigger}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            role="menu"
            initial={{ opacity: 0, y: -4, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -4, scale: 0.98 }}
            transition={{ duration: 0.13, ease: "easeOut" }}
            className="absolute right-0 z-30 mt-1.5 w-56 overflow-hidden rounded-lg border border-line bg-panel shadow-xl shadow-black/40"
          >
            {items.map((item) => (
              <button
                key={item.label}
                role="menuitem"
                onClick={() => {
                  item.onSelect();
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[13px] transition-colors hover:bg-panel-2"
              >
                <span className="text-muted">{item.icon}</span>
                <span className="flex-1">{item.label}</span>
                {item.hint && <span className="font-mono text-[11px] text-muted">{item.hint}</span>}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
