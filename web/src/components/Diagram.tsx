"use client";

import { useEffect, useRef, useState } from "react";

let initialised = false;

/**
 * Renders a Mermaid diagram, or shows its source if it will not parse.
 *
 * Mermaid is imported dynamically: it is ~500KB, and most pages never show a
 * diagram. A failed render falls back to the source rather than the library's
 * red error box, because a reader can still learn something from four lines
 * of `flowchart TD` and nothing at all from "Syntax error in text".
 */
export default function Diagram({ source }: { source: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        if (!initialised) {
          mermaid.initialize({
            startOnLoad: false,
            theme: "base",
            securityLevel: "strict", // no click handlers or raw HTML from generated text
            fontFamily: "var(--font-geist-sans), sans-serif",
            themeVariables: {
              background: "transparent",
              primaryColor: "#161a22",
              primaryTextColor: "#edf1f7",
              primaryBorderColor: "#242a35",
              lineColor: "#5eead4",
              secondaryColor: "#101319",
              tertiaryColor: "#1e232d",
              fontSize: "14px",
            },
          });
          initialised = true;
        }

        const id = `diagram-${Math.random().toString(36).slice(2)}`;
        const { svg } = await mermaid.render(id, source);
        if (!cancelled && container.current) container.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [source]);

  if (failed) {
    return (
      <pre className="overflow-x-auto rounded-lg border border-line bg-panel-2 p-4 font-mono text-[12px] text-muted">
        {source}
      </pre>
    );
  }

  return (
    <div
      ref={container}
      className="flex justify-center overflow-x-auto rounded-lg border border-line bg-panel-2 p-5 [&_svg]:max-w-full"
    />
  );
}
