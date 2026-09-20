"use client";

import { motion, useInView } from "motion/react";
import { useRef } from "react";

const STAGES = [
  { name: "Validate", note: "Refuses what isn't a research topic" },
  { name: "Plan", note: "3–5 self-contained sub-questions" },
  { name: "Research", note: "Web and your documents, in parallel", fan: true },
  { name: "Write", note: "Every claim cited to a numbered source" },
  { name: "Fact-check", note: "Each statement checked against the evidence" },
  { name: "Review", note: "Scored for grounding, coverage, coherence" },
];

/**
 * The pipeline, drawn. It is the thing that makes this different from a chat
 * box, so it is worth showing rather than describing — and the fan-out is the
 * part people ask about.
 */
export default function Pipeline() {
  const container = useRef<HTMLDivElement>(null);
  const inView = useInView(container, { once: true, margin: "-80px" });

  return (
    <section ref={container} className="py-6">
      <p className="eyebrow mb-6">How a report is made</p>

      <ol className="relative grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {STAGES.map((stage, index) => (
          <motion.li
            key={stage.name}
            initial={{ opacity: 0, y: 14 }}
            animate={inView ? { opacity: 1, y: 0 } : {}}
            transition={{ delay: index * 0.07, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className="group card relative overflow-hidden p-4"
          >
            {/* A light that follows the reveal order, so the row reads as a
                sequence rather than six identical boxes. */}
            <motion.span
              initial={{ scaleX: 0 }}
              animate={inView ? { scaleX: 1 } : {}}
              transition={{ delay: index * 0.07 + 0.15, duration: 0.6 }}
              style={{ transformOrigin: "left" }}
              className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-accent/60 to-transparent"
            />

            <div className="flex items-baseline gap-2.5">
              <span className="font-mono text-[11px] text-accent/70">{String(index + 1).padStart(2, "0")}</span>
              <h3 className="text-[15px] text-text">{stage.name}</h3>
              {stage.fan && (
                <span className="ml-auto flex items-center gap-1" aria-label="runs in parallel">
                  {[0, 1, 2].map((dot) => (
                    <motion.span
                      key={dot}
                      animate={{ opacity: [0.25, 1, 0.25] }}
                      transition={{ repeat: Infinity, duration: 1.6, delay: dot * 0.2 }}
                      className="h-1 w-1 rounded-full bg-accent"
                    />
                  ))}
                </span>
              )}
            </div>
            <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted">{stage.note}</p>
          </motion.li>
        ))}
      </ol>

      <motion.p
        initial={{ opacity: 0 }}
        animate={inView ? { opacity: 1 } : {}}
        transition={{ delay: 0.5 }}
        className="mt-4 font-mono text-[11.5px] text-muted"
      >
        A draft that fails either review goes back to the writer, up to three times.
      </motion.p>
    </section>
  );
}
