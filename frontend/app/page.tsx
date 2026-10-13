"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { m, AnimatePresence } from "motion/react";
import { useAutoAnimate } from "@formkit/auto-animate/react";
import { MultiSelect } from "react-multi-select-component";
import { Activity, Database, Play, RefreshCcw, FolderSync, PlayCircle, ExternalLink, ChevronDown, ChevronRight } from "lucide-react";
import StatsCard from "@/components/StatsCard";
import { SearchInput } from "@/components/SearchInput";

// ── Motion variants ──────────────────────────────────────────────────────────
const kpiContainerVariants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.08, delayChildren: 0.05 } },
};
const kpiCardVariants = {
  hidden:  { opacity: 0, y: 20, scale: 0.97 },
  visible: { opacity: 1, y: 0,  scale: 1, transition: { duration: 0.4, ease: [0.34, 1.26, 0.64, 1] as const } },
};

interface Project {
  id: number;
  token: string;
  title: string;
  main_site?: string;
  website?: string;
  stored_records: number;
  metadata?: {
    region?: string;
    country?: string;
    brand?: string;
    total_pages?: number;
    status?: string;
  } | null;
  last_run?: {
    run_token: string;
    status: string;
    pages_requested?: number;
    pages_scraped?: number;
    data_ready?: number;
    start_time?: string;
    end_time?: string;
    updated_at?: string;
  } | null;
}

interface ProjectGroup {
  website: string;
  projects: Project[];
  totalPages: number;
  runningCount: number;
  completedCount: number;
}

interface GroupRunResult {
  status: "success" | "partial" | "error";
  summary: string;
  failedProjects: string[];
}

interface FiltersResponse {
  filters?: {
    regions?: string[];
    countries?: string[];
    brands?: string[];
    websites?: string[];
  };
}

interface MultiSelectOption {
  label: string;
  value: string;
}

export default function HomePage() {
  const didInitialLoad = useRef(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [countries, setCountries] = useState<string[]>([]);
  const [brands, setBrands] = useState<string[]>([]);
  const [websites, setWebsites] = useState<string[]>([]);
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [selectedBrands, setSelectedBrands] = useState<string[]>([]);
  const [selectedWebsites, setSelectedWebsites] = useState<string[]>([]);
  const [appliedRegions, setAppliedRegions] = useState<string[]>([]);
  const [appliedCountries, setAppliedCountries] = useState<string[]>([]);
  const [appliedBrands, setAppliedBrands] = useState<string[]>([]);
  const [appliedWebsites, setAppliedWebsites] = useState<string[]>([]);
  const [selectedRunStatus, setSelectedRunStatus] = useState<"all" | "running" | "complete" | "idle">("all");
  const [loading, setLoading] = useState(true);
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [filtersLoading, setFiltersLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [runningGroups, setRunningGroups] = useState<Record<string, boolean>>({});
  const [runningGroupProgress, setRunningGroupProgress] = useState<Record<string, { done: number; total: number }>>({});
  const [groupRunResults, setGroupRunResults] = useState<Record<string, GroupRunResult | undefined>>({});
  const [runningProjects, setRunningProjects] = useState<Record<string, boolean>>({});
  const [projectRunFeedback, setProjectRunFeedback] = useState<Record<string, { type: "success" | "error"; message: string } | null>>({});

  const extractDomain = (input: string | undefined | null): string => {
    const raw = (input || "").trim().toLowerCase();
    if (!raw) return "unknown";

    try {
      const withProtocol = raw.includes("://") ? raw : `https://${raw}`;
      const hostname = new URL(withProtocol).hostname || raw;
      return hostname.replace(/^www\./, "") || "unknown";
    } catch {
      const cleaned = raw.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
      return cleaned || "unknown";
    }
  };

  const getProjectDomain = (project: Project): string => {
    return extractDomain(project.website || project.main_site || project.title);
  };

  const normalizeRunStatus = (status: string | undefined | null): "running" | "complete" | "idle" | "other" => {
    const value = String(status || "").trim().toLowerCase();
    if (!value || value === "idle") return "idle";
    if (["running", "queued", "initialized", "starting", "in_progress"].includes(value)) return "running";
    if (["complete", "completed", "success", "succeeded"].includes(value)) return "complete";
    return "other";
  };

  const toSelectOptions = (values: string[]): MultiSelectOption[] => {
    return values.map((value) => ({ label: value, value }));
  };

  const selectedOptions = (values: string[]): MultiSelectOption[] => {
    return values.map((value) => ({ label: value, value }));
  };

  const areSameSelections = (left: string[], right: string[]): boolean => {
    if (left.length !== right.length) return false;
    return left.every((value, index) => value === right[index]);
  };

  // Helper to check if a run is recent (within 1 hour)
  const isRecentRun = (timestamp: string | undefined): boolean => {
    if (!timestamp) return false;
    try {
      const runTime = new Date(timestamp).getTime();
      const oneHourAgo = Date.now() - 60 * 60 * 1000; // 1 hour in milliseconds
      return runTime > oneHourAgo;
    } catch {
      return false;
    }
  };

  const runStatusFilteredProjects = projects.filter((project) => {
    const normalizedStatus = normalizeRunStatus(project.last_run?.status);
    const matchesStatus = (() => {
      if (selectedRunStatus === "all") return true;
      if (selectedRunStatus === "idle") return normalizedStatus === "idle";
      return normalizedStatus === selectedRunStatus;
    })();
    const matchesSearch = !searchQuery || project.title.toLowerCase().includes(searchQuery.toLowerCase()) || (project.website || project.main_site || "").toLowerCase().includes(searchQuery.toLowerCase());
    return matchesStatus && matchesSearch;
  });

  const groupedProjects: ProjectGroup[] = Object.values(
    runStatusFilteredProjects.reduce<Record<string, ProjectGroup>>((acc, project) => {
      const domain = getProjectDomain(project);
      if (!acc[domain]) {
        acc[domain] = {
          website: domain,
          projects: [],
          totalPages: 0,
          runningCount: 0,
          completedCount: 0,
        };
      }

      acc[domain].projects.push(project);
      acc[domain].totalPages += Number(project.metadata?.total_pages || 0);
      // Only count as "running" if status is 'running' AND it's a recent run (< 1 hour old)
      // This prevents showing stale completed runs as active entries
      const lastRunTimestamp = project.last_run?.updated_at || project.last_run?.end_time || project.last_run?.start_time;
      const normalizedStatus = normalizeRunStatus(project.last_run?.status);
      if (normalizedStatus === "running" && isRecentRun(lastRunTimestamp)) acc[domain].runningCount += 1;
      if (normalizedStatus === "complete" && isRecentRun(lastRunTimestamp)) acc[domain].completedCount += 1;
      return acc;
    }, {})
  ).sort((a, b) => a.website.localeCompare(b.website));

  const toggleGroup = (website: string) => {
    setExpandedGroups((prev) => ({ ...prev, [website]: !prev[website] }));
  };

  const getGroupStatus = (group: ProjectGroup): { label: string; className: string } => {
    if (group.runningCount > 0) {
      return { label: `${group.runningCount} Running`, className: "badge-running" };
    }
    if (group.completedCount === group.projects.length && group.projects.length > 0) {
      return { label: "Completed", className: "badge-complete" };
    }
    return { label: "Idle", className: "badge-idle" };
  };

  const runAllForGroup = async (group: ProjectGroup) => {
    const key = group.website;
    if (runningGroups[key]) return;

    const projectTokens = group.projects.map((project) => project.token);
    if (!projectTokens.length) {
      setGroupRunResults((prev) => ({
        ...prev,
        [key]: {
          status: "error",
          summary: `No projects available in ${group.website}.`,
          failedProjects: [],
        },
      }));
      return;
    }

    const total = projectTokens.length;
    const failures: string[] = [];
    let successful = 0;

    try {
      setRunningGroups((prev) => ({ ...prev, [key]: true }));
      setRunningGroupProgress((prev) => ({ ...prev, [key]: { done: 0, total } }));
      setGroupRunResults((prev) => ({ ...prev, [key]: undefined }));

      for (let index = 0; index < group.projects.length; index += 1) {
        const project = group.projects[index];

        const response = await fetch("/api/projects/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: project.token,
            pages: Number(project.metadata?.total_pages || 1),
          }),
        });

        const data = await response.json().catch(() => ({}));
        if (response.ok) {
          successful += 1;
        } else {
          failures.push(`${project.title || project.token}: ${data.error || "Failed to start run"}`);
        }

        setRunningGroupProgress((prev) => ({
          ...prev,
          [key]: { done: index + 1, total },
        }));
      }

      const failed = failures.length;
      const status: GroupRunResult["status"] = failed === 0 ? "success" : successful === 0 ? "error" : "partial";
      setGroupRunResults((prev) => ({
        ...prev,
        [key]: {
          status,
          summary: `Run All finished for ${group.website}: ${successful}/${total} started, ${failed} failed.`,
          failedProjects: failures,
        },
      }));
      await loadProjects();
    } catch (groupRunError) {
      setGroupRunResults((prev) => ({
        ...prev,
        [key]: {
          status: "error",
          summary: groupRunError instanceof Error ? groupRunError.message : "Failed to run group",
          failedProjects: [],
        },
      }));
    } finally {
      setRunningGroups((prev) => ({ ...prev, [key]: false }));
      setRunningGroupProgress((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
    }
  };

  const runSingleProject = async (project: Project) => {
    const { token: projectToken } = project;
    if (runningProjects[projectToken]) return;
    try {
      setRunningProjects((prev) => ({ ...prev, [projectToken]: true }));
      setProjectRunFeedback((prev) => ({ ...prev, [projectToken]: null }));
      const response = await fetch("/api/projects/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: projectToken }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.error || "Failed to run project");
      }
      setProjectRunFeedback((prev) => ({
        ...prev,
        [projectToken]: { type: "success", message: `Run started: ${data.run_token || ""}` },
      }));
      await loadProjects();
    } catch (runError) {
      setProjectRunFeedback((prev) => ({
        ...prev,
        [projectToken]: {
          type: "error",
          message: runError instanceof Error ? runError.message : "Failed to run project",
        },
      }));
    } finally {
      setRunningProjects((prev) => ({ ...prev, [projectToken]: false }));
    }
  };

  useEffect(() => {
    if (didInitialLoad.current) return;
    didInitialLoad.current = true;
    void Promise.all([loadFilters(), loadProjects()]).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.hidden) return;
      void loadProjects(undefined, { silent: true });
    }, 30000);
    return () => window.clearInterval(interval);
  }, [appliedRegions, appliedCountries, appliedBrands, appliedWebsites]);

  const loadFilters = async () => {
    const response = await fetch("/api/filters");
    const data = (await response.json()) as FiltersResponse;
    setRegions(data.filters?.regions || []);
    setCountries(data.filters?.countries || []);
    setBrands(data.filters?.brands || []);
    setWebsites(data.filters?.websites || []);
  };

  const loadProjects = async (overrideFilters?: {
    regions?: string[];
    countries?: string[];
    brands?: string[];
    websites?: string[];
  }, options?: { silent?: boolean }) => {
    const silent = options?.silent === true;
    try {
      if (!silent) {
        setProjectsLoading(true);
        setError(null);
        setMessage(null);
      }
      const query = new URLSearchParams({
        page: "1",
        limit: "200",
        filter_keyword: "(msa pricing)",
      });
      const regions = overrideFilters?.regions ?? appliedRegions;
      const countries = overrideFilters?.countries ?? appliedCountries;
      const brands = overrideFilters?.brands ?? appliedBrands;
      const websites = overrideFilters?.websites ?? appliedWebsites;
      regions.forEach((value) => query.append("region", value));
      countries.forEach((value) => query.append("country", value));
      brands.forEach((value) => query.append("brand", value));
      websites.forEach((value) => query.append("website", value));

      const response = await fetch(`/api/projects?${query.toString()}`, {
        method: "GET",
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to load projects");
      }
      const nextProjects = data.projects || [];
      setProjects(nextProjects);
      setProjectRunFeedback((prev) => {
        const next = { ...prev };
        const statusByToken = new Map<string, string>();
        nextProjects.forEach((project: Project) => {
          statusByToken.set(project.token, normalizeRunStatus(project.last_run?.status));
        });

        Object.entries(next).forEach(([token, feedback]) => {
          // Auto-hide transient success toast once run leaves running state.
          if (feedback?.type === "success") {
            const normalizedStatus = statusByToken.get(token);
            if (normalizedStatus && normalizedStatus !== "running") {
              delete next[token];
            }
          }
        });

        return next;
      });
    } catch (loadError) {
      if (!silent) {
        setError(loadError instanceof Error ? loadError.message : "Failed to load projects");
      }
    } finally {
      if (!silent) {
        setProjectsLoading(false);
      }
    }
  };

  const syncProjects = async () => {
    try {
      setSyncing(true);
      setError(null);
      setMessage(null);
      const payload = {
        page: 1,
        limit: 200,
        region: appliedRegions.length > 0 ? appliedRegions : undefined,
        country: appliedCountries.length > 0 ? appliedCountries : undefined,
        brand: appliedBrands.length > 0 ? appliedBrands : undefined,
        website: appliedWebsites.length > 0 ? appliedWebsites : undefined,
      };
      const response = await fetch('/api/projects/sync-msa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to sync projects");
      }
      setProjects(data.projects || []);
      setMessage(data.message || "MSA projects synced");
      await loadFilters();
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "Failed to sync projects");
    } finally {
      setSyncing(false);
    }
  };

  const runningCount = projects.filter((project) => normalizeRunStatus(project.last_run?.status) === "running").length;
  const completedCount = projects.filter((project) => normalizeRunStatus(project.last_run?.status) === "complete").length;
  const storedCount = projects.reduce((sum, project) => sum + (project.stored_records || 0), 0);

  // AutoAnimate — zero-config list mutations for group rows
  const [listRef] = useAutoAnimate<HTMLDivElement>({ duration: 250, easing: "ease-out" });

  const getStatusBadge = (status: string | undefined) => {
    const normalizedStatus = normalizeRunStatus(status);
    if (normalizedStatus === "idle") return <span className="badge-idle"><span className="status-dot idle" />Idle</span>;
    if (normalizedStatus === "running") return <span className="badge-running"><span className="status-dot running animate-pulse" />Running</span>;
    if (normalizedStatus === "complete") return <span className="badge-complete"><span className="status-dot complete" />Complete</span>;
    return <span className="badge-idle">{status}</span>;
  };

  const FILTER_TABS: { key: "all" | "running" | "complete" | "idle"; label: string; count: number }[] = [
    { key: "all",      label: "All Projects", count: projects.length },
    { key: "running",  label: "Running",      count: runningCount },
    { key: "complete", label: "Completed",    count: completedCount },
    { key: "idle",     label: "Idle",         count: projects.filter((p) => normalizeRunStatus(p.last_run?.status) === "idle").length },
  ];
  const hasGroupRunInFlight = Object.values(runningGroups).some(Boolean);
  const hasProjectRunInFlight = Object.values(runningProjects).some(Boolean);
  const dashboardActionLocked = projectsLoading || syncing || hasGroupRunInFlight || hasProjectRunInFlight;
  const hasPendingFilterChanges =
    !areSameSelections(selectedRegions, appliedRegions) ||
    !areSameSelections(selectedCountries, appliedCountries) ||
    !areSameSelections(selectedBrands, appliedBrands) ||
    !areSameSelections(selectedWebsites, appliedWebsites);
  const showDashboardLoader = loading || filtersLoading;

  const applyFilters = async () => {
    if (!hasPendingFilterChanges || dashboardActionLocked) return;
    const nextRegions = [...selectedRegions];
    const nextCountries = [...selectedCountries];
    const nextBrands = [...selectedBrands];
    const nextWebsites = [...selectedWebsites];
    setAppliedRegions(nextRegions);
    setAppliedCountries(nextCountries);
    setAppliedBrands(nextBrands);
    setAppliedWebsites(nextWebsites);
    try {
      setFiltersLoading(true);
      await loadProjects({
        regions: nextRegions,
        countries: nextCountries,
        brands: nextBrands,
        websites: nextWebsites,
      });
    } finally {
      setFiltersLoading(false);
    }
  };

  const resetFilters = async () => {
    if (dashboardActionLocked) return;
    setSelectedRegions([]);
    setSelectedCountries([]);
    setSelectedBrands([]);
    setSelectedWebsites([]);
    setAppliedRegions([]);
    setAppliedCountries([]);
    setAppliedBrands([]);
    setAppliedWebsites([]);
    try {
      setFiltersLoading(true);
      await loadProjects({
        regions: [],
        countries: [],
        brands: [],
        websites: [],
      });
    } finally {
      setFiltersLoading(false);
    }
  };

  return (
    <main className="app-page relative flex-1 overflow-y-auto">
      {showDashboardLoader && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 backdrop-blur-[1px]">
          <div className="app-surface flex items-center gap-3 rounded-xl px-5 py-4 shadow-lg">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
            <span className="app-copy text-sm">Loading projects... this may take a while.</span>
          </div>
        </div>
      )}
      {/* ── Top bar ───────────────────────────────────────────── */}
      <div className="app-page-header sticky top-0 z-30 flex items-center justify-between gap-4 px-8 py-3">
        <div className="app-copy-weak flex items-center gap-2 text-sm">
          <span className="app-title font-medium">Dashboard</span>
        </div>
        <div className="flex items-center gap-3">
          <SearchInput
            value={searchQuery}
            onChange={setSearchQuery}
            placeholder="Search projects…"
          />
          <button
            onClick={() => void loadProjects()}
            disabled={dashboardActionLocked}
            className="btn-ghost h-8 px-3 text-xs"
          >
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </button>
          <button
            onClick={() => void syncProjects()}
            disabled={dashboardActionLocked}
            className="btn-primary h-8 px-4 text-xs"
          >
            <FolderSync className="h-3.5 w-3.5" />
            {syncing ? "Fetching…" : "Fetch MSA Projects"}
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-6">
        {/* ── Page title ─────────────────────────────────────── */}
        <div>
          <p className="section-label mb-1">Scraping Orchestration</p>
          <h1 className="app-title text-[28px] font-semibold tracking-[-0.02em]">ParseHub Monitoring System</h1>
        </div>

        {/* ── KPI strip ──────────────────────────────────────── */}
        <m.div
          variants={kpiContainerVariants}
          initial="hidden"
          animate="visible"
          className="grid grid-cols-2 gap-4 xl:grid-cols-4"
        >
          {[
            { title: "Total Projects",  value: projects.length, icon: <Database className="h-4 w-4" />, accentColor: "blue"  as const, delay: 0   },
            { title: "Running",         value: runningCount,    icon: <Activity className="h-4 w-4" />, accentColor: "green" as const, delay: 80,  pulse: true },
            { title: "Completed Runs",  value: completedCount,  icon: <PlayCircle className="h-4 w-4" />, accentColor: "amber" as const, delay: 160 },
            { title: "Stored Records",  value: storedCount,     icon: <Database className="h-4 w-4" />, accentColor: "blue"  as const, delay: 240 },
          ].map((stat) => (
            <m.div key={stat.title} variants={kpiCardVariants}>
              <StatsCard {...stat} />
            </m.div>
          ))}
        </m.div>

        {/* ── Alert banner ───────────────────────────────────── */}
        {(error || message) && (
          <div className={`app-alert rounded-lg px-4 py-3 text-sm ${error ? "app-alert-error" : "app-alert-success"}`}>
            {error || message}
          </div>
        )}

        {/* ── Filters ────────────────────────────────────────── */}
        <div className="saas-card space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {/* Filter tabs — Motion layoutId sliding pill */}
            <div className="app-segmented flex w-fit gap-1 p-1">
              {FILTER_TABS.map(({ key, label, count }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setSelectedRunStatus(key)}
                  className={`app-segmented-item relative z-10 rounded-lg px-3 py-1.5 text-[13px] font-medium transition-colors ${selectedRunStatus === key ? "app-segmented-item-active" : ""}`}
                >
                  {selectedRunStatus === key && (
                    <m.span
                      layoutId="activeFilterTab"
                      className="app-surface absolute inset-0 rounded-lg shadow-sm"
                      style={{ zIndex: -1 }}
                      transition={{ type: "spring", stiffness: 400, damping: 35 }}
                    />
                  )}
                  {label}
                  <m.span
                    animate={{
                      backgroundColor: selectedRunStatus === key ? "var(--accent-primary)" : "var(--bg-subtle)",
                      color: selectedRunStatus === key ? "var(--text-on-accent)" : "var(--text-secondary)",
                    }}
                    transition={{ duration: 0.2 }}
                    className="ml-1.5 text-[10px] font-mono rounded-full px-1.5 py-0.5 inline-block"
                  >
                    {count}
                  </m.span>
                </button>
              ))}
            </div>

            <button
              onClick={() => setShowFilters((c) => !c)}
              className="btn-ghost h-8 px-3 text-xs shrink-0"
            >
              {showFilters ? "Hide Filters" : "Advanced Filters"}
            </button>
          </div>

          {showFilters && (
            <div className="grid gap-3 pt-1 md:grid-cols-2 xl:grid-cols-4">
              <MultiSelect
                className="dashboard-multiselect"
                options={toSelectOptions(regions)}
                value={selectedOptions(selectedRegions)}
                onChange={(options: MultiSelectOption[]) => setSelectedRegions(options.map((option: MultiSelectOption) => option.value))}
                labelledBy="Select Regions"
                hasSelectAll={false}
                overrideStrings={{ selectSomeItems: "All Regions" }}
              />
              <MultiSelect
                className="dashboard-multiselect"
                options={toSelectOptions(countries)}
                value={selectedOptions(selectedCountries)}
                onChange={(options: MultiSelectOption[]) => setSelectedCountries(options.map((option: MultiSelectOption) => option.value))}
                labelledBy="Select Countries"
                hasSelectAll={false}
                overrideStrings={{ selectSomeItems: "All Countries" }}
              />
              <MultiSelect
                className="dashboard-multiselect"
                options={toSelectOptions(brands)}
                value={selectedOptions(selectedBrands)}
                onChange={(options: MultiSelectOption[]) => setSelectedBrands(options.map((option: MultiSelectOption) => option.value))}
                labelledBy="Select Brands"
                hasSelectAll={false}
                overrideStrings={{ selectSomeItems: "All Brands" }}
              />
              <MultiSelect
                className="dashboard-multiselect"
                options={toSelectOptions(websites)}
                value={selectedOptions(selectedWebsites)}
                onChange={(options: MultiSelectOption[]) => setSelectedWebsites(options.map((option: MultiSelectOption) => option.value))}
                labelledBy="Select Websites"
                hasSelectAll={false}
                overrideStrings={{ selectSomeItems: "All Websites" }}
              />
              <div className="md:col-span-2 xl:col-span-4 flex justify-end">
                <button
                  type="button"
                  onClick={() => void resetFilters()}
                  disabled={
                    dashboardActionLocked ||
                    (selectedRegions.length === 0 &&
                      selectedCountries.length === 0 &&
                      selectedBrands.length === 0 &&
                      selectedWebsites.length === 0 &&
                      appliedRegions.length === 0 &&
                      appliedCountries.length === 0 &&
                      appliedBrands.length === 0 &&
                      appliedWebsites.length === 0)
                  }
                  className="btn-ghost h-8 px-4 text-xs"
                >
                  Reset Filters
                </button>
                <button
                  type="button"
                  onClick={() => void applyFilters()}
                  disabled={dashboardActionLocked || !hasPendingFilterChanges}
                  className="btn-primary h-8 px-4 text-xs ml-2"
                >
                  Apply Filters
                </button>
              </div>
            </div>
          )}
        </div>

        {/* ── Projects table ─────────────────────────────────── */}
        <div className="app-table-shell overflow-hidden rounded-xl">
          {/* Sticky table header */}
          <div className="app-table-head grid grid-cols-[2fr_140px_100px_160px] border-b border-[var(--border-default)] px-5 py-3 text-[11px] font-semibold uppercase tracking-[0.08em]">
            <div>Project / Domain</div>
            <div>Status</div>
            <div>Pages</div>
            <div className="text-right">Actions</div>
          </div>
          {loading && (
            <div className="app-copy flex items-center justify-center py-16 text-sm">
              Loading projects…
            </div>
          )}

          {!loading && groupedProjects.length === 0 && (
            <div className="app-empty-state flex flex-col items-center justify-center py-16 text-center">
              <Database className="app-copy-weak mb-3 h-8 w-8" />
              <p className="app-copy text-sm font-medium">No projects found</p>
              <p className="app-copy-weak mt-1 text-xs">Use "Fetch MSA Projects" to sync from ParseHub</p>
            </div>
          )}

          <div ref={listRef}>
          {groupedProjects.map((group, groupIdx) => {
            const expanded = expandedGroups[group.website] ?? false;
            const groupStatus = getGroupStatus(group);
            const currentProgress = runningGroupProgress[group.website];
            const groupResult = groupRunResults[group.website];
            const isGroupRunning = Boolean(runningGroups[group.website]);
            const groupHasActiveRun = group.projects.some((project) => normalizeRunStatus(project.last_run?.status) === "running");

            return (
              <div
                key={group.website}
                className={`border-b border-[var(--border-default)] last:border-b-0 ${groupIdx % 2 === 0 ? "bg-transparent" : "bg-[var(--bg-surface)]/55"}`}
              >
                {/* Group row */}
                <div className="group/row grid grid-cols-[2fr_140px_100px_160px] items-center gap-3 px-5 py-3.5 transition hover:bg-[var(--bg-table-row-hover)]">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.website)}
                      className="app-icon-button flex h-5 w-5 shrink-0 items-center justify-center rounded transition"
                    >
                      {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                    </button>
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.website)}
                      className="min-w-0 text-left"
                    >
                      <p className="app-title truncate text-sm font-semibold">{group.website}</p>
                      <p className="app-copy-weak text-xs">{group.projects.length} {group.projects.length === 1 ? "project" : "projects"}</p>
                    </button>
                  </div>

                  <div>
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${groupStatus.className}`}>
                      {groupStatus.label}
                    </span>
                  </div>

                  <div>
                    <span className="app-copy font-mono text-sm">{group.totalPages}</span>
                  </div>

                  <div className="flex justify-end gap-2 opacity-0 group-hover/row:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={() => void runAllForGroup(group)}
                      disabled={dashboardActionLocked || isGroupRunning || groupHasActiveRun}
                      className="btn-primary h-7 px-3 text-xs"
                    >
                      <PlayCircle className="h-3 w-3" />
                      {isGroupRunning
                        ? `${currentProgress?.done ?? 0}/${currentProgress?.total ?? group.projects.length}`
                        : groupHasActiveRun
                        ? "Running"
                        : "Run All"}
                    </button>
                  </div>
                </div>

                {/* Group result toast */}
                {groupResult && (
                  <div className={`app-alert mx-5 mb-2 rounded-lg px-3 py-2 text-xs ${groupResult.status === "success" ? "app-alert-success" : groupResult.status === "partial" ? "app-alert-warning" : "app-alert-error"}`}>
                    {groupResult.summary}
                    {groupResult.failedProjects.length > 0 && <span className="ml-2 opacity-70">Failed: {groupResult.failedProjects.join(", ")}</span>}
                  </div>
                )}

                {/* Expanded project rows */}
                <AnimatePresence initial={false}>
                  {expanded && group.projects.map((project, i) => (
                    <m.div
                      key={project.token}
                      initial={{ opacity: 0, y: -6 }}
                      animate={{ opacity: 1, y: 0, transition: { delay: i * 0.04, duration: 0.2, ease: "easeOut" } }}
                      exit={{ opacity: 0, y: -6, transition: { duration: 0.12 } }}
                    >
                    <div
                      className="group/proj grid grid-cols-[2fr_140px_100px_160px] items-center gap-3 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] px-5 py-3 transition hover:bg-[var(--bg-table-row-hover)]"
                    >
                      <div className="min-w-0 pl-8">
                        <p className="app-title truncate text-sm font-medium">{project.title}</p>
                        <p className="app-copy-weak mt-0.5 truncate font-mono text-xs">{project.token}</p>
                      </div>
                      <div>{getStatusBadge(project.last_run?.status)}</div>
                      <div>
                        <span className="app-copy font-mono text-sm">{project.metadata?.total_pages ?? 1}</span>
                      </div>
                      <div
                        className={`flex justify-end gap-1.5 transition-opacity ${
                          runningProjects[project.token]
                            ? "opacity-100"
                            : "opacity-0 group-hover/proj:opacity-100"
                        }`}
                      >
                      {(() => {
                        const projectHasActiveRun = normalizeRunStatus(project.last_run?.status) === "running";
                        return (
                          <button
                            type="button"
                            onClick={() => void runSingleProject(project)}
                            disabled={Boolean(runningProjects[project.token]) || projectHasActiveRun}
                            className="btn-primary h-7 px-3 text-xs"
                          >
                            <Play className="h-3 w-3" />
                            {runningProjects[project.token] ? (
                              "Running…"
                            ) : projectHasActiveRun ? (
                              <span className="text-[10px]">Running</span>
                            ) : (
                              "Run"
                            )}
                          </button>
                        );
                      })()}
                        <Link
                          href={`/projects/${project.token}`}
                          className="btn-secondary h-7 px-3 text-xs"
                        >
                          <ExternalLink className="h-3 w-3" />
                          Open
                        </Link>
                      </div>
                    </div>
                    {projectRunFeedback[project.token] && (
                      <div
                        className={`app-alert mx-5 mb-2 pl-8 rounded-lg px-3 py-2 text-xs ${
                          projectRunFeedback[project.token]?.type === "success"
                            ? "app-alert-success"
                            : "app-alert-error"
                        }`}
                      >
                        {projectRunFeedback[project.token]?.message}
                      </div>
                    )}
                    </m.div>
                  ))}
                </AnimatePresence>
              </div>
            );
          })}
          </div>
        </div>
      </div>
      <style jsx global>{`
        .dashboard-multiselect {
          --rmsc-bg: var(--bg-surface);
          --rmsc-border: var(--border-default);
          --rmsc-main: var(--accent-primary);
          --rmsc-hover: var(--bg-subtle);
          --rmsc-selected: color-mix(in srgb, var(--accent-primary) 18%, var(--bg-surface));
          --rmsc-gray: var(--text-secondary);
        }
        .dashboard-multiselect .dropdown-container {
          background: var(--bg-surface);
          border-color: var(--border-default);
          color: var(--text-primary);
          min-height: 36px;
          border-radius: 8px;
        }
        .dashboard-multiselect .gray {
          color: var(--text-secondary) !important;
        }
        .dashboard-multiselect .dropdown-heading-value {
          color: var(--text-primary);
        }
        .dashboard-multiselect .dropdown-content .panel-content {
          background: var(--bg-elevated, var(--bg-surface));
          border: 1px solid var(--border-default);
          color: var(--text-primary);
          border-radius: 8px;
          box-shadow: 0 10px 26px rgba(0, 0, 0, 0.28);
        }
        .dashboard-multiselect .options,
        .dashboard-multiselect .options li,
        .dashboard-multiselect .select-item,
        .dashboard-multiselect .item-renderer,
        .dashboard-multiselect .item-renderer span {
          background: transparent;
          color: var(--text-primary);
        }
        .dashboard-multiselect .select-item:hover {
          background: var(--bg-subtle);
        }
        .dashboard-multiselect .select-item.selected {
          background: color-mix(in srgb, var(--accent-primary) 18%, var(--bg-surface));
        }
        .dashboard-multiselect .search {
          background: transparent;
          color: var(--text-primary);
        }
        .dashboard-multiselect .search input {
          color: var(--text-primary);
        }
        .dashboard-multiselect .search input::placeholder {
          color: var(--text-secondary);
        }
      `}</style>
    </main>
  );
}
