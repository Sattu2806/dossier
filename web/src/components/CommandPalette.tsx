"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Clock, CornerDownLeft, Search, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import type { Run } from "@/lib/backend";

type Command = { id: string; label: string; hint?: string; icon: React.ReactNode; run: () => void };

/**
 * ⌘K. Two reasons it earns its place here rather than being decoration:
 * starting a search is the app's only real verb, and the history is a list
 * you want to jump into by name rather than scroll.
 */
export default function CommandPalette({ recent }: { recent: Run[] }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((previous) => !previous);
      }
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (open) {
      setQuery("");
      setIndex(0);
    }
  }, [open]);

  const commands = useMemo<Command[]>(() => {
    const base: Command[] = [
      {
        id: "new",
        label: query.trim() ? `Research “${query.trim()}”` : "New research",
        hint: "Home",
        icon: <Sparkles size={15} />,
        run: () => {
          const topic = query.trim();
          router.push(topic ? `/?topic=${encodeURIComponent(topic)}` : "/");
        },
      },
      { id: "history", label: "Open history", hint: "All reports", icon: <Clock size={15} />, run: () => router.push("/history") },
    ];

    const needle = query.trim().toLowerCase();
    const matches = recent
      .filter((run) => !needle || run.topic.toLowerCase().includes(needle))
      .slice(0, 6)
      .map<Command>((run) => ({
        id: run.id,
        label: run.topic,
        hint: run.status,
        icon: <ArrowRight size={15} />,
        run: () => router.push(`/runs/${run.id}`),
      }));

    return [...base, ...matches];
  }, [query, recent, router]);

  useEffect(() => {
    setIndex((current) => Math.min(current, Math.max(0, commands.length - 1)));
  }, [commands.length]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setIndex((current) => (current + 1) % commands.length);
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setIndex((current) => (current - 1 + commands.length) % commands.length);
    }
    if (event.key === "Enter") {
      event.preventDefault();
      commands[index]?.run();
      setOpen(false);
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 px-4 pt-[14vh] backdrop-blur-sm"
        >
          <motion.div
            initial={{ opacity: 0, y: -12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 460, damping: 34 }}
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-xl overflow-hidden rounded-2xl border border-line bg-panel shadow-[var(--shadow-float)]"
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search size={16} className="text-muted" />
              <input
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Search a topic, or type a new one…"
                className="flex-1 bg-transparent py-4 text-[15px] outline-none placeholder:text-muted/70"
              />
              <kbd className="rounded border border-line px-1.5 py-0.5 font-mono text-[10px] text-muted">esc</kbd>
            </div>

            <ul className="max-h-[52vh] overflow-y-auto p-1.5">
              {commands.map((command, position) => (
                <li key={command.id}>
                  <button
                    onMouseEnter={() => setIndex(position)}
                    onClick={() => {
                      command.run();
                      setOpen(false);
                    }}
                    className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px] transition-colors ${
                      position === index ? "bg-panel-2 text-text" : "text-text-dim"
                    }`}
                  >
                    <span className={position === index ? "text-accent" : "text-muted"}>{command.icon}</span>
                    <span className="flex-1 truncate">{command.label}</span>
                    {command.hint && <span className="font-mono text-[10.5px] text-muted">{command.hint}</span>}
                    {position === index && <CornerDownLeft size={13} className="text-muted" />}
                  </button>
                </li>
              ))}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
