"use client";
import { useState } from "react";
import { useSpring, animated } from "@react-spring/web";
import { Search } from "lucide-react";

interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

export function SearchInput({ value, onChange, placeholder = "Search…" }: SearchInputProps) {
  const [focused, setFocused] = useState(false);

  const spring = useSpring({
    width: focused ? 280 : 200,
    boxShadow: focused
      ? "0 0 0 2px rgba(59,130,246,0.3)"
      : "0 0 0 0px rgba(59,130,246,0)",
    config: { mass: 1, tension: 320, friction: 28 },
  });

  return (
    <animated.div
      style={{
        ...spring,
        height: "2rem",
        borderRadius: "0.5rem",
        border: "1px solid var(--border-default)",
        background: "var(--bg-input)",
        display: "flex",
        alignItems: "center",
        paddingLeft: "0.625rem",
        paddingRight: "0.625rem",
        overflow: "hidden",
      }}
    >
      <Search className="mr-2 h-3.5 w-3.5 shrink-0 app-copy-weak" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        placeholder={placeholder}
        style={{
          background: "transparent",
          fontSize: "0.8125rem",
          outline: "none",
          width: "100%",
          color: "var(--text-primary)",
        }}
        className="placeholder:app-copy-weak"
      />
    </animated.div>
  );
}
