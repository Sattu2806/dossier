"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check } from "lucide-react";
import { createContext, useCallback, useContext, useState } from "react";

type Toast = { id: number; message: string };
const ToastContext = createContext<(message: string) => void>(() => {});

/** Confirmation that an action happened. Without it, "Export → Markdown"
 *  silently drops a file somewhere and the click feels broken. */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current, { id, message }]);
    setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 2600);
  }, []);

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 flex-col items-center gap-2">
        <AnimatePresence>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.98 }}
              transition={{ type: "spring", stiffness: 420, damping: 32 }}
              className="flex items-center gap-2 rounded-full border border-line bg-panel-2/95 px-4 py-2 text-[13px] shadow-[var(--shadow-float)] backdrop-blur"
            >
              <Check size={13} className="text-accent" />
              {toast.message}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
