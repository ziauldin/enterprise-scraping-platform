"use client";
import { useEffect, useRef } from "react";
import { gsap } from "@/lib/gsap";

interface AnimatedNumberProps {
  value: number;
  duration?: number;
  delay?: number;
}

export function AnimatedNumber({ value, duration = 0.8, delay = 0 }: AnimatedNumberProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(0);

  useEffect(() => {
    if (!ref.current) return;
    const obj = { val: prev.current };
    gsap.to(obj, {
      val: value,
      duration,
      delay,
      ease: "power2.out",
      onUpdate() {
        if (ref.current) {
          ref.current.textContent = Math.round(obj.val).toLocaleString();
        }
      },
      onComplete() {
        prev.current = value;
      },
    });
  }, [value, duration, delay]);

  return <span ref={ref}>{prev.current.toLocaleString()}</span>;
}
