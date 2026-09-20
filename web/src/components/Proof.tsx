"use client";

import { animate, motion, useInView } from "motion/react";
import { useEffect, useRef, useState } from "react";

/**
 * The measured results, from the 27-topic eval set in the repository. Real
 * numbers, and the honest one is `0 invented citations` — that is a property
 * of the design (numbers are assigned by code, the model never sees a URL),
 * not a boast about the model.
 */
const FACTS = [
  { value: 4.85, suffix: "/5", label: "Groundedness", note: "judged by a separate model" },
  { value: 27, suffix: "", label: "Topics evaluated", note: "including adversarial ones" },
  { value: 0, suffix: "", label: "Invented citations", note: "numbers assigned by code" },
  { value: 11, suffix: "s", label: "Median report", note: "planned, searched, written" },
];

function Counter({ to, suffix }: { to: number; suffix: string }) {
  const [shown, setShown] = useState(0);
  const element = useRef<HTMLSpanElement>(null);
  const inView = useInView(element, { once: true });

  useEffect(() => {
    if (!inView) return;
    // Counting up is the point: a number that lands has more weight than one
    // that was always there.
    const controls = animate(0, to, {
      duration: 1.1,
      ease: [0.22, 1, 0.36, 1],
      onUpdate: (value) => setShown(value),
    });
    return () => controls.stop();
  }, [inView, to]);

  const decimals = to % 1 !== 0 ? 2 : 0;
  return (
    <span ref={element} className="display text-[34px] text-text">
      {shown.toFixed(decimals)}
      <span className="text-[20px] text-muted">{suffix}</span>
    </span>
  );
}

export default function Proof() {
  return (
    <section className="py-6">
      <p className="eyebrow mb-6">Measured, not claimed</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {FACTS.map((fact, index) => (
          <motion.div
            key={fact.label}
            initial={{ opacity: 0, y: 12 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, margin: "-60px" }}
            transition={{ delay: index * 0.06, duration: 0.5 }}
            className="card p-5"
          >
            <Counter to={fact.value} suffix={fact.suffix} />
            <p className="mt-2 text-[13.5px] text-text">{fact.label}</p>
            <p className="mt-0.5 text-[12px] text-muted">{fact.note}</p>
          </motion.div>
        ))}
      </div>
    </section>
  );
}
