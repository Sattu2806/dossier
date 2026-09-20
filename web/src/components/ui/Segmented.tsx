"use client";

import { motion } from "motion/react";

type Option<T extends string> = { value: T; label: string; count?: number };

/**
 * A segmented control whose indicator slides between options.
 *
 * The movement comes from `layoutId`: both states render the same element
 * identity, so the library animates between their measured positions rather
 * than us hand-writing offsets that break the moment a label changes length.
 */
export default function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Option<T>[];
  value: T;
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="inline-flex gap-1 rounded-lg border border-line bg-panel p-1">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.value)}
            className={`relative rounded-md px-3 py-1.5 text-[13px] transition-colors ${
              active ? "text-text" : "text-muted hover:text-text"
            }`}
          >
            {active && (
              <motion.span
                layoutId="segmented-active"
                className="absolute inset-0 rounded-md bg-panel-2 ring-1 ring-line"
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
              />
            )}
            <span className="relative flex items-center gap-1.5">
              {option.label}
              {option.count !== undefined && (
                <span className="rounded-full bg-bg/60 px-1.5 font-mono text-[10.5px] text-muted">
                  {option.count}
                </span>
              )}
            </span>
          </button>
        );
      })}
    </div>
  );
}
