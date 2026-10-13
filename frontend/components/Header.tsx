"use client";

import { useEffect, useState } from "react";
import { Layers, Clock, Database, Home, FileUp, Settings, TableProperties } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/ThemeToggle";

export default function Header() {
  const [time, setTime] = useState<string>("");
  const [date, setDate] = useState<string>("");
  const pathname = usePathname();

  useEffect(() => {
    const now = new Date();
    setTime(
      now.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      }),
    );
    setDate(
      now.toLocaleDateString("en-US", {
        weekday: "long",
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    );
  }, []);

  const isActive = (path: string) => pathname === path;
  const navLinkClass = (path: string) =>
    `focus-ring-cyan inline-flex items-center gap-2 rounded-xl border-b-2 px-4 py-2.5 text-sm font-semibold tracking-[0.01em] transition-all duration-200 ${
      isActive(path)
        ? "border border-teal-700/35 border-b-[#1B7B7B] bg-teal-50 text-teal-800 shadow-[0_8px_20px_rgba(0,0,0,0.03)]"
        : "border border-transparent border-b-transparent text-[#0A2E5C] hover:bg-slate-50 hover:text-[#1B7B7B] hover:border-b-[#1B7B7B]"
    }`;

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border-default)] bg-[var(--bg-surface)]/95 backdrop-blur-xl shadow-[0_8px_20px_rgba(0,0,0,0.03)] transition-colors duration-200">
      <div className="container mx-auto px-6">
        {/* Main Header */}
        <div className="relative flex items-center justify-between overflow-hidden border-b border-[var(--border-default)] py-5 transition-colors duration-200">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_10%,rgba(10,46,92,0.07),transparent_38%)]" />
          <div className="pointer-events-none absolute bottom-0 left-0 h-12 w-full bg-[radial-gradient(140%_70%_at_50%_100%,rgba(27,123,123,0.12),transparent_70%)]" />
          <div className="flex items-center gap-4">
            <div className="animate-soft-glow flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-[#0A2E5C] to-[#1B7B7B] shadow-lg shadow-[#0A2E5C]/20 ring-1 ring-white/40">
              <Layers className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="bg-gradient-to-r from-[#0A2E5C] via-[#0A2E5C] to-[#1B7B7B] bg-clip-text text-2xl font-bold tracking-tight text-transparent">
                ParseHub Dashboard
              </h1>
              <p className="mt-0.5 flex items-center gap-2 text-sm text-[var(--text-secondary)] transition-colors duration-200">
                <Database className="w-3.5 h-3.5 text-[#1B7B7B]" />
                Manual ParseHub runs backed by Snowflake
              </p>
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="flex items-center gap-2 text-sm font-semibold text-[#0A2E5C] transition-colors duration-200">
                <Clock className="w-4 h-4 text-[#1B7B7B]" />
                {time}
              </div>
              <p className="text-xs text-[var(--text-secondary)] mt-0.5 transition-colors duration-200">{date}</p>
            </div>
            <ThemeToggle />
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex flex-wrap items-center gap-2 py-3">
          <Link href="/" className={navLinkClass("/")}>
            <Home className="w-4 h-4" />
            Home
          </Link>
          <Link href="/projects" className={navLinkClass("/projects")}>
            <Settings className="w-4 h-4" />
            Projects
          </Link>
          <Link href="/import-metadata" className={navLinkClass("/import-metadata")}>
            <FileUp className="w-4 h-4" />
            Import
          </Link>
          <Link href="/metadata" className={navLinkClass("/metadata")}>
            <TableProperties className="w-4 h-4" />
            Metadata
          </Link>
        </nav>
      </div>
    </header>
  );
}
