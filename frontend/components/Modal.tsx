"use client";

import { X } from "lucide-react";
import { ReactNode } from "react";

interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  size?: "small" | "medium" | "large" | "xlarge";
}

export default function Modal({
  isOpen,
  onClose,
  title,
  children,
  size = "medium",
}: ModalProps) {
  if (!isOpen) return null;

  const sizeClasses = {
    small: "max-w-md",
    medium: "max-w-2xl",
    large: "max-w-4xl",
    xlarge: "max-w-6xl",
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto animate-in fade-in duration-200" style={{ background: "var(--bg-overlay)", backdropFilter: "blur(6px)" }}>
      <div className="min-h-screen px-4 py-8 flex items-center justify-center">
        <div
          className={`${sizeClasses[size]} app-surface my-auto flex max-h-[calc(100vh-4rem)] w-full flex-col rounded-2xl shadow-2xl ring-1 ring-cyan-500/10 animate-in zoom-in-95 duration-200 backdrop-blur-xl`}
        >
          <div className="flex shrink-0 items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-elevated)] p-6">
            <h2 className="app-title text-xl font-bold">
              {title}
            </h2>
            <button
              onClick={onClose}
              className="app-icon-button rounded-lg p-2 transition-all duration-200"
              aria-label="Close modal"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
          <div className="p-6 overflow-y-auto custom-scrollbar flex-1 min-h-0">
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
