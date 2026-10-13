"use client";

import { useEffect } from "react";

/** Poll interval when there are pending/active scheduled runs (ms). */
const FAST_MS = 10_000;
/** Poll interval when nothing is pending — avoids unnecessary traffic (ms). */
const SLOW_MS = 60_000;
/** Number of consecutive idle responses before switching to the slow interval. */
const IDLE_THRESHOLD = 3;

/**
 * Set NEXT_PUBLIC_HEARTBEAT_ENABLED=false in frontend/.env to disable this
 * component entirely during root-cause tracing.  Default is enabled.
 */
const HEARTBEAT_ENABLED =
  process.env.NEXT_PUBLIC_HEARTBEAT_ENABLED !== "false";

export default function ScheduledRunsHeartbeat() {
  useEffect(() => {
    if (!HEARTBEAT_ENABLED) {
      console.warn(
        "[ScheduledRunsHeartbeat] Heartbeat is disabled via NEXT_PUBLIC_HEARTBEAT_ENABLED=false"
      );
      return;
    }

    let cancelled = false;
    let idleCount = 0;

    const trigger = async () => {
      if (cancelled) return;
      try {
        const res = await fetch("/api/scheduled-runs/trigger", {
          method: "POST",
          cache: "no-store",
        });
        if (res.ok) {
          const data: { result?: { processed?: number } } = await res
            .json()
            .catch(() => ({}));
          const processed = data?.result?.processed ?? 0;
          // Reset idle counter whenever work was actually dispatched.
          idleCount = processed > 0 ? 0 : idleCount + 1;
        }
      } catch {
        // Intentionally ignore heartbeat failures to avoid disrupting UI.
      } finally {
        if (!cancelled) {
          // Slow down polling after several consecutive idle responses so the
          // heartbeat does not keep calling trigger for already-completed tasks.
          const delay = idleCount >= IDLE_THRESHOLD ? SLOW_MS : FAST_MS;
          window.setTimeout(trigger, delay);
        }
      }
    };

    // Fire immediately on mount, then self-reschedule via setTimeout.
    void trigger();

    return () => {
      cancelled = true;
    };
  }, []);

  return null;
}
