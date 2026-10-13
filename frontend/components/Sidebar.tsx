"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { m } from "motion/react";
import {
  Layers,
  Home,
  TableProperties,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";

const NAV_ITEMS = [
  { href: "/",                label: "Dashboard",  icon: Home },
  { href: "/metadata",        label: "Metadata",   icon: TableProperties },
  { href: "/scheduled-runs",  label: "Scheduled Runs", icon: TableProperties },
];

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();
  const width = collapsed ? 64 : 220;

  return (
    <aside
      style={{
        width,
        minWidth: width,
        transition: "width 280ms cubic-bezier(0.4,0,0.2,1), min-width 280ms cubic-bezier(0.4,0,0.2,1)",
      }}
      className="app-sidebar-shell relative z-40 flex min-h-screen shrink-0 flex-col overflow-hidden"
    >
      {/* Header */}
      <div className="app-sidebar-header flex h-16 shrink-0 items-center justify-between border-b px-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-[#3B82F6] to-[#1d4ed8] shadow-lg">
            <Layers className="h-4 w-4 text-white" />
          </div>
          {!collapsed && (
            <span className="app-sidebar-title truncate text-sm font-bold tracking-tight">
              ParseHub
            </span>
          )}
        </div>
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="app-icon-button flex h-7 w-7 shrink-0 items-center justify-center rounded-md transition"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <ChevronLeft className="h-3.5 w-3.5" />
          )}
        </button>
      </div>

      {/* Main nav */}
      <nav className="flex-1 overflow-hidden py-4 px-2 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              className={`app-sidebar-nav-link relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "app-sidebar-nav-active"
                  : "hover:text-[var(--text-primary)]"
              }`}
            >
              {isActive && (
                <m.span
                  layoutId="navActiveBg"
                  className="app-sidebar-active-surface absolute inset-0 rounded-lg border shadow-sm"
                  transition={{ type: "spring", stiffness: 380, damping: 35 }}
                />
              )}
              <Icon
                className="h-4 w-4 shrink-0 stroke-[1.5] relative z-10"
                style={{ color: isActive ? "#3B82F6" : "inherit" }}
              />
              {!collapsed && (
                <span className="truncate relative z-10">{label}</span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* Bottom nav */}
      <div className="app-sidebar-footer mt-auto border-t px-2 py-3">
        <div
          className={`app-sidebar-card flex items-center rounded-lg px-2 py-2 transition-all ${
            collapsed ? "justify-center" : "justify-between gap-3"
          }`}
        >
          {!collapsed && (
            <div className="min-w-0">
              <p className="app-copy-weak truncate text-xs font-semibold uppercase tracking-[0.12em]">
                Appearance
              </p>
              <p className="app-copy truncate text-sm font-medium">
                Theme mode
              </p>
            </div>
          )}
          <ThemeToggle />
        </div>
      </div>
    </aside>
  );
}
