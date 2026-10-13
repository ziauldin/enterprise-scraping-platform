"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw, Trash2 } from "lucide-react";

type SortKey = "project_name" | "scheduled_run_time" | "status" | "last_updated";

interface ScheduledRun {
  id: number;
  project_token: string;
  project_name?: string | null;
  schedule_type?: "one_time" | "recurring" | null;
  recurrence_frequency?: "daily" | "weekly" | "monthly" | null;
  recurrence_weekday?: number | null;
  recurrence_day_of_month?: number | null;
  local_time?: string | null;
  rule_summary?: string | null;
  scheduled_run_time?: string | null;
  scheduled_run_time_local?: string | null;
  scheduled_run_time_utc?: string | null;
  timezone?: string | null;
  run_token?: string | null;
  status: string;
  last_updated?: string | null;
  error_message?: string | null;
}

const STATUS_OPTIONS = ["Scheduled"];

const rankStatus = (value: string) => {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "scheduled") return 1;
  if (normalized === "in progress") return 2;
  if (normalized === "completed") return 3;
  if (normalized === "failed") return 4;
  return 5;
};

const parseDate = (value?: string | null) => {
  if (!value) return Number.NEGATIVE_INFINITY;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : Number.NEGATIVE_INFINITY;
};

export default function ScheduledRunsPage() {
  const [runs, setRuns] = useState<ScheduledRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [deletingIds, setDeletingIds] = useState<Record<number, boolean>>({});
  const [sortBy, setSortBy] = useState<SortKey>("scheduled_run_time");
  const [sortDesc, setSortDesc] = useState(true);
  const [statusFilter, setStatusFilter] = useState("Scheduled");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 25;

  const formatLocal = (value?: string | null) => {
    if (!value) return "-";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const recurrenceSummary = (run: ScheduledRun) => {
    if ((run.schedule_type || "one_time") !== "recurring") return "One time";
    if (run.rule_summary) return run.rule_summary;
    if (run.recurrence_frequency === "daily") return `Every day at ${run.local_time || "--:--"}`;
    if (run.recurrence_frequency === "weekly") return `Every week on ${run.recurrence_weekday ?? "?"} at ${run.local_time || "--:--"}`;
    if (run.recurrence_frequency === "monthly") return `Every month on day ${run.recurrence_day_of_month ?? "?"} at ${run.local_time || "--:--"}`;
    return "Recurring";
  };

  const loadRuns = useCallback(async (silent = false) => {
    try {
      if (!silent) {
        setLoading(true);
      }
      setError(null);
      const response = await fetch(`/api/scheduled-runs?limit=1000&status=${encodeURIComponent(statusFilter)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to load scheduled runs");
      }
      setRuns((payload.data || []) as ScheduledRun[]);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load scheduled runs");
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [statusFilter]);

  useEffect(() => {
    void loadRuns(false);
    const interval = window.setInterval(() => {
      void loadRuns(true);
    }, 10000);
    return () => window.clearInterval(interval);
  }, [loadRuns]);

  const filteredRuns = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    const afterFilter = runs.filter((run) => {
      const matchesStatus = statusFilter === "All" || String(run.status || "").toLowerCase() === statusFilter.toLowerCase();
      if (!matchesStatus) return false;
      if (!normalizedQuery) return true;

      const haystack = [
        run.project_name,
        run.project_token,
        run.run_token,
        run.status,
        run.scheduled_run_time,
        run.scheduled_run_time_local,
        run.scheduled_run_time_utc,
        run.error_message,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(normalizedQuery);
    });

    const sorted = [...afterFilter].sort((a, b) => {
      let result = 0;
      if (sortBy === "project_name") {
        result = String(a.project_name || a.project_token || "").localeCompare(String(b.project_name || b.project_token || ""));
      } else if (sortBy === "status") {
        result = rankStatus(a.status) - rankStatus(b.status);
      } else if (sortBy === "last_updated") {
        result = parseDate(a.last_updated) - parseDate(b.last_updated);
      } else {
        const aTime = parseDate(a.scheduled_run_time || a.scheduled_run_time_local || a.scheduled_run_time_utc);
        const bTime = parseDate(b.scheduled_run_time || b.scheduled_run_time_local || b.scheduled_run_time_utc);
        result = aTime - bTime;
      }
      return sortDesc ? -result : result;
    });

    return sorted;
  }, [runs, query, sortBy, sortDesc, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredRuns.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageRows = filteredRuns.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  useEffect(() => {
    setPage(1);
  }, [query, statusFilter, sortBy, sortDesc]);

  const onDeleteRun = async (id: number) => {
    const confirmed = window.confirm("Delete this scheduled run? It will no longer be triggered.");
    if (!confirmed) return;

    try {
      setDeletingIds((prev) => ({ ...prev, [id]: true }));
      setError(null);
      setMessage(null);

      const response = await fetch(`/api/scheduled-runs/${id}`, {
        method: "DELETE",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to delete scheduled run");
      }

      setRuns((prev) => prev.filter((run) => run.id !== id));
      setMessage("Scheduled run deleted.");
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : "Failed to delete scheduled run");
    } finally {
      setDeletingIds((prev) => ({ ...prev, [id]: false }));
    }
  };

  const onSort = (key: SortKey) => {
    if (sortBy === key) {
      setSortDesc((prev) => !prev);
      return;
    }
    setSortBy(key);
    setSortDesc(key !== "project_name");
  };

  return (
    <main className="app-page flex-1 overflow-y-auto">
      <div className="app-page-header px-8 py-6">
        <p className="section-label">Automation</p>
        <div className="mt-1 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="app-title text-[28px] font-semibold tracking-[-0.02em]">Scheduled Runs</h1>
          <button onClick={() => void loadRuns(false)} disabled={loading} className="btn-secondary h-9 px-4 text-sm disabled:opacity-40">
            <RefreshCcw className="h-3.5 w-3.5" />
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-5">
        {message && <div className="app-alert app-alert-success rounded-lg px-4 py-3 text-sm">{message}</div>}
        {error && <div className="app-alert app-alert-error rounded-lg px-4 py-3 text-sm">{error}</div>}

        <div className="saas-card space-y-4">
          <div className="grid gap-3 md:grid-cols-4">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search project, token, status"
              className="saas-select h-9 text-sm"
            />
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="saas-select h-9 text-sm">
              {STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>{option}</option>
              ))}
            </select>
            <select value={sortBy} onChange={(event) => onSort(event.target.value as SortKey)} className="saas-select h-9 text-sm">
              <option value="scheduled_run_time">Sort: Scheduled Time</option>
              <option value="project_name">Sort: Project</option>
              <option value="status">Sort: Status</option>
              <option value="last_updated">Sort: Last Updated</option>
            </select>
            <button onClick={() => setSortDesc((prev) => !prev)} className="btn-secondary h-9 px-4 text-sm">
              Order: {sortDesc ? "Descending" : "Ascending"}
            </button>
          </div>

          {loading ? (
            <div className="app-copy flex items-center justify-center gap-2 py-12 text-sm">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
              Loading scheduled runs...
            </div>
          ) : pageRows.length === 0 ? (
            <div className="app-empty-state rounded-lg px-4 py-8 text-center text-sm">
              No scheduled runs found.
            </div>
          ) : (
            <div className="app-table-shell overflow-hidden rounded-lg">
              <div className="overflow-x-auto">
                <table className="saas-table">
                  <thead>
                    <tr>
                      <th>
                        <button onClick={() => onSort("project_name")} className="font-semibold">Project Name</button>
                      </th>
                      <th>Type</th>
                      <th>Rule</th>
                      <th>
                        <button onClick={() => onSort("scheduled_run_time")} className="font-semibold">Next Run</button>
                      </th>
                      <th>Timezone</th>
                      <th>
                        <button onClick={() => onSort("status")} className="font-semibold">Status</button>
                      </th>
                      <th>Run Token</th>
                      <th>
                        <button onClick={() => onSort("last_updated")} className="font-semibold">Last Updated</button>
                      </th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageRows.map((run) => {
                      const scheduledValue = run.scheduled_run_time || run.scheduled_run_time_local || run.scheduled_run_time_utc;
                      return (
                        <tr key={run.id}>
                          <td>{run.project_name || run.project_token}</td>
                          <td>{(run.schedule_type || "one_time") === "recurring" ? "Recurring" : "One time"}</td>
                          <td>{recurrenceSummary(run)}</td>
                          <td>{formatLocal(scheduledValue)}</td>
                          <td>{run.timezone || "-"}</td>
                          <td>{run.status || "-"}</td>
                          <td className="font-mono text-[11px]">{run.run_token || "-"}</td>
                          <td>{formatLocal(run.last_updated)}</td>
                          <td>
                            <button
                              onClick={() => void onDeleteRun(run.id)}
                              disabled={!!deletingIds[run.id]}
                              className="app-danger-button inline-flex h-8 items-center gap-1 rounded-md px-2 text-xs disabled:opacity-50"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                              {deletingIds[run.id] ? "Deleting..." : "Delete"}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="app-copy flex items-center justify-between pt-1 text-sm">
            <span>
              Showing {pageRows.length} of {filteredRuns.length} runs
            </span>
            <div className="flex items-center gap-2">
              <button onClick={() => setPage((prev) => Math.max(1, prev - 1))} disabled={currentPage <= 1} className="btn-secondary h-8 px-3 text-xs disabled:opacity-40">
                Previous
              </button>
              <span>
                Page {currentPage} of {totalPages}
              </span>
              <button onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))} disabled={currentPage >= totalPages} className="btn-secondary h-8 px-3 text-xs disabled:opacity-40">
                Next
              </button>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
