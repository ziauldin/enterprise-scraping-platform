"use client";

import { ReactNode, useEffect, useRef } from "react";
import { useSpring, animated } from "@react-spring/web";
import { gsap } from "@/lib/gsap";

interface StatsCardProps {
  title: string;
  value: number | string;
  icon: ReactNode;
  /** accent-primary = blue, accent-success = green, accent-warning = amber, accent-danger = red */
  accentColor?: "blue" | "green" | "amber" | "red";
  /** show pulsing indicator (for Running > 0) */
  pulse?: boolean;
  /** animation delay in ms */
  delay?: number;
  /** legacy color prop – ignored, kept for compat */
  color?: string;
}

const ACCENT: Record<NonNullable<StatsCardProps["accentColor"]>, { border: string; text: string }> = {
  blue:  { border: "border-t-[var(--accent-primary)]", text: "text-[var(--status-info-text)]" },
  green: { border: "border-t-[var(--accent-success)]", text: "text-[var(--status-success-text)]" },
  amber: { border: "border-t-[var(--accent-warning)]", text: "text-[var(--status-warning-text)]" },
  red:   { border: "border-t-[var(--accent-danger)]", text: "text-[var(--status-danger-text)]" },
};

export default function StatsCard({
  title,
  value,
  icon,
  accentColor = "blue",
  pulse = false,
  delay = 0,
}: StatsCardProps) {
  const isNum = typeof value === "number";
  const acc = ACCENT[accentColor];

  // ── GSAP count-up ────────────────────────────────────────
  const numRef = useRef<HTMLSpanElement>(null);
  const prevVal = useRef(0);

  useEffect(() => {
    if (!isNum || !numRef.current) return;
    const target = value as number;
    const obj = { val: prevVal.current };
    gsap.to(obj, {
      val: target,
      duration: 0.9,
      delay: delay / 1000,
      ease: "power2.out",
      onUpdate() {
        if (numRef.current) {
          numRef.current.textContent = Math.round(obj.val).toLocaleString();
        }
      },
      onComplete() {
        prevVal.current = target;
      },
    });
  }, [value]);           // eslint-disable-line react-hooks/exhaustive-deps

  // ── react-spring 3-D tilt ────────────────────────────────
  const [spring, api] = useSpring(() => ({
    rotateX: 0,
    rotateY: 0,
    scale: 1,
    config: { mass: 1, tension: 280, friction: 30 },
  }));

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientY - rect.top  - rect.height / 2) / 14;
    const y = -(e.clientX - rect.left - rect.width  / 2) / 14;
    api.start({ rotateX: x, rotateY: y, scale: 1.025 });
  };

  return (
    <animated.div
      style={{ ...spring, transformStyle: "preserve-3d" as const, perspective: "800px" }}
      onMouseMove={handleMouseMove}
      onMouseLeave={() => api.start({ rotateX: 0, rotateY: 0, scale: 1 })}
      className={`group app-surface relative cursor-default overflow-hidden rounded-xl border border-t-2 p-5 ${acc.border}`}
    >
      {/* Icon — top right, muted */}
      <div className="absolute right-4 top-4 app-copy-weak transition-colors group-hover:text-[var(--text-secondary)]">
        {icon}
      </div>

      {/* Label */}
      <p className="section-label mb-3">{title}</p>

      {/* Value */}
      <div className="flex items-center gap-3">
        <p className={`text-[40px] font-bold leading-none tracking-tight ${acc.text}`}>
          {isNum ? (
            <span ref={numRef}>0</span>
          ) : (
            <span>{String(value)}</span>
          )}
        </p>
        {pulse && (value as number) > 0 && (
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[var(--accent-success)] opacity-75" />
            <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-[var(--accent-success)]" />
          </span>
        )}
      </div>
    </animated.div>
  );
}
