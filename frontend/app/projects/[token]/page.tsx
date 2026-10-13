"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft, AlertCircle, CheckCircle, Database, Download, Play, RefreshCcw, Square } from "lucide-react";
import { Bar, BarChart, CartesianGrid, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

interface CumulativeSession {
  project_run_cumulative_id: string;
  status: string;
  is_active: number;
  started_at?: string;
  completed_at?: string;
  created_by_run_token?: string;
  last_run_token?: string;
  total_runs_in_session?: number;
}

interface ProjectDetail {
  id: number;
  token: string;
  title: string;
  main_site?: string;
  owner_email?: string;
  stored_records: number;
  metadata?: {
    project_name?: string;
    website_type?: "Collective" | "Individual" | null;
    region?: string;
    country?: string;
    brand?: string;
    website_url?: string;
    total_pages?: number;
    total_products?: number;
    current_page_scraped?: number;
    current_product_scraped?: number;
    next_page_url?: string;
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
  } | null;
  runs?: Array<{
    run_token: string;
    status: string;
    pages_requested?: number;
    pages_scraped?: number;
    data_ready?: number;
    start_time?: string;
    end_time?: string;
  }>;
  run_stats?: {
    total_runs: number;
    completed_runs: number;
    active_runs: number;
    pages_scraped: number;
  };
  current_cumulative_session?: CumulativeSession | null;
  completion_progress?: {
    website_type?: "Collective" | "Individual" | null;
    formula?: "collective" | "individual" | null;
    confirmed_pages?: number;
    live_pages?: number;
    has_active_live_run?: boolean;
    active_live_run_token?: string | null;
    active_live_run_status?: string | null;
    active_live_run_cumulative_id?: string | null;
    project_run_cumulative_id?: string | null;
    displayed_progress_pages?: number;
    numerator_pages_scraped?: number;
    denominator?: number;
    total_pages?: number;
    total_products?: number;
    progress_percent?: number;
    progress_percent_raw?: number;
    status?: "live_in_progress" | "in_progress_no_active_run" | "in_progress" | "complete" | "no_run_progress" | "invalid_website_type" | "invalid_denominator" | "inconsistent_data";
    inconsistent?: boolean;
  } | null;
  automation_state?: {
    automation_enabled?: boolean;
    scheduler_enabled?: boolean;
    in_automated_progression?: boolean;
    latest_ingestion?: {
      run_token?: string;
      status?: string;
      inserted_count?: number;
      updated_at?: string;
    } | null;
    last_automation_event_at?: string | null;
  } | null;
  next_scheduled_run?: ScheduledRun | null;
}

interface ProductStats {
  statistics?: {
    total_products: number;
    total_runs_with_data: number;
    latest_extraction?: string;
    max_page_scraped?: number;
  };
}

type PreviewRowLimit = "10" | "20" | "50" | "all";

interface StoredDataRow {
  project_run_cumulative_id?: string | null;
  run_token?: string | null;
  name?: string | null;
  part_number?: string | null;
  brand?: string | null;
  product_url?: string | null;
  list_price?: string | number | null;
  sale_price?: string | number | null;
  case_unit_price?: string | number | null;
  currency?: string | null;
  country?: string | null;
  page_number?: number | null;
  extraction_date?: string | null;
}

interface CumulativeSummaryGroup {
  project_run_cumulative_id: string;
  status: string;
  is_active: number;
  total_stored_records: number;
  distinct_page_count: number;
  last_run_token?: string | null;
  max_page_number?: number | null;
  first_extraction_date?: string | null;
  last_extraction_date?: string | null;
  total_runs_in_session?: number | null;
}

interface ResumeStatus {
  success: boolean;
  resumable: boolean;
  project_found: boolean;
  metadata_found: boolean;
  max_page_scraped?: number;
  total_pages?: number;
  next_page_number?: number;
  generated_next_page_url?: string;
  project_complete?: boolean;
  inconsistent?: boolean;
  active_project_run_cumulative_id?: string | null;
  message: string;
  error?: string | null;
}

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
  scheduled_run_time_utc?: string | null;
  scheduled_run_time_local?: string | null;
  timezone?: string | null;
  run_token?: string | null;
  error_message?: string | null;
  last_updated?: string | null;
  status: string;
}

type ScheduleMode = "one_time" | "recurring";
type RecurrenceFrequency = "daily" | "weekly" | "monthly";

const WEEKDAY_OPTIONS = [
  { value: 0, label: "Monday" },
  { value: 1, label: "Tuesday" },
  { value: 2, label: "Wednesday" },
  { value: 3, label: "Thursday" },
  { value: 4, label: "Friday" },
  { value: 5, label: "Saturday" },
  { value: 6, label: "Sunday" },
];

const DAY_OF_MONTH_OPTIONS = Array.from({ length: 31 }, (_, i) => i + 1);
const ACTIVE_RUN_STATUSES = new Set(["running", "queued", "initialized"]);
const COMPLETED_RUN_STATUSES = new Set(["complete", "completed", "success", "succeeded"]);
const normalizeRunStatus = (status: string | null | undefined): string => String(status || "").toLowerCase();

export default function ProjectDetailPage() {
  const params = useParams();
  const token = params.token as string;
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [productStats, setProductStats] = useState<ProductStats | null>(null);
  const [productStatsLoading, setProductStatsLoading] = useState(false);
  const [previewData, setPreviewData] = useState<StoredDataRow[]>([]);
  const [cumulativeSummaries, setCumulativeSummaries] = useState<CumulativeSummaryGroup[]>([]);
  const [storedDataRequested, setStoredDataRequested] = useState(false);
  const [storedDataError, setStoredDataError] = useState<string | null>(null);
  const [latestCumulativeId, setLatestCumulativeId] = useState<string | null>(null);
  const [selectedCumulativeId, setSelectedCumulativeId] = useState<string | null>(null);
  const [previewRowLimit, setPreviewRowLimit] = useState<PreviewRowLimit>("20");
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [resumeStatus, setResumeStatus] = useState<ResumeStatus | null>(null);
  const [resumeStatusLoading, setResumeStatusLoading] = useState(false);
  const [resumeStatusError, setResumeStatusError] = useState<string | null>(null);
  const [schedulePickerOpen, setSchedulePickerOpen] = useState(false);
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("one_time");
  const [scheduleTimezone, setScheduleTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
  );
  const [scheduleLocalTime, setScheduleLocalTime] = useState("");
  const [recurrenceFrequency, setRecurrenceFrequency] = useState<RecurrenceFrequency>("daily");
  const [recurrenceWeekday, setRecurrenceWeekday] = useState<number>(0);
  const [recurrenceDayOfMonth, setRecurrenceDayOfMonth] = useState<number>(1);
  const [recurrenceLocalTime, setRecurrenceLocalTime] = useState("09:00");
  const [scheduleSaving, setScheduleSaving] = useState(false);
  const [scheduledRuns, setScheduledRuns] = useState<ScheduledRun[]>([]);
  const [scheduledRunsLoading, setScheduledRunsLoading] = useState(false);

  const formatDisplayDateTime = (value?: string | null) => {
    if (!value) return "Unknown extraction time";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "Unknown extraction time";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`;
  };

  const formatScheduledTimeLocal = (value?: string | null) => {
    if (!value) return null;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return null;
    return parsed.toLocaleString(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  };

  const getLocalDateTimeInputValue = (offsetMinutes = 5) => {
    const now = new Date(Date.now() + offsetMinutes * 60 * 1000);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
  };

  const timezoneOptions = useMemo(() => {
    const intlAny = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    if (typeof intlAny.supportedValuesOf === "function") {
      return intlAny.supportedValuesOf("timeZone");
    }
    return [
      "UTC",
      "Asia/Karachi",
      "Asia/Dubai",
      "Asia/Kolkata",
      "Europe/London",
      "Europe/Berlin",
      "America/New_York",
      "America/Chicago",
      "America/Denver",
      "America/Los_Angeles",
      "Australia/Sydney",
    ];
  }, []);

  const recurrenceSummary = (run: ScheduledRun) => {
    if ((run.schedule_type || "one_time") !== "recurring") return "One time";
    if (run.rule_summary) return run.rule_summary;
    if (run.recurrence_frequency === "daily") {
      return `Every day at ${run.local_time || "--:--"}`;
    }
    if (run.recurrence_frequency === "weekly") {
      const match = WEEKDAY_OPTIONS.find((opt) => opt.value === Number(run.recurrence_weekday));
      return `Every week on ${match?.label || "Unknown"} at ${run.local_time || "--:--"}`;
    }
    if (run.recurrence_frequency === "monthly") {
      return `Every month on day ${run.recurrence_day_of_month || "?"} at ${run.local_time || "--:--"}`;
    }
    return "Recurring";
  };

  const loadResumeStatus = async (silent = true) => {
    try {
      if (!silent) {
        setResumeStatusLoading(true);
      }
      setResumeStatusError(null);
      const response = await fetch(`/api/projects/${token}/resume-status`, { cache: "no-store" });
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        const text = await response.text();
        throw new Error(`Resume status API returned non-JSON response (${response.status}): ${text.slice(0, 100)}`);
      }

      const data = await response.json() as ResumeStatus;
      if (!response.ok) {
        throw new Error(data.error || data.message || "Failed to load resume status");
      }

      setResumeStatus(data);
    } catch (statusError) {
      setResumeStatusError(statusError instanceof Error ? statusError.message : "Failed to load resume status");
    } finally {
      if (!silent) {
        setResumeStatusLoading(false);
      }
    }
  };

  const loadProject = async () => {
    try {
      setError(null);
      setProductStats(null);
      setProductStatsLoading(true);
      const response = await fetch(`/api/projects/${token}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to load project");
      }
      const nextProject = data.data as ProjectDetail;
      setProject(nextProject);
      setLoading(false);

      // Do not block initial page render on stats; fetch it in background.
      if (nextProject.id) {
        void (async () => {
          const statsFetchStartedAt = Date.now();
          try {
            const statsResponse = await fetch(`/api/products/${nextProject.id}/stats`);
            if (statsResponse.ok) {
              setProductStats(await statsResponse.json());
            }
          } catch {
            // Keep page interactive even if stats endpoint is slow.
          } finally {
            const elapsed = Date.now() - statsFetchStartedAt;
            const minSkeletonMs = 1500;
            if (elapsed < minSkeletonMs) {
              await new Promise((resolve) => window.setTimeout(resolve, minSkeletonMs - elapsed));
            }
            setProductStatsLoading(false);
          }
        })();
      } else {
        setProductStatsLoading(false);
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load project");
      setLoading(false);
      setProductStatsLoading(false);
    }
  };

  const pollProjectState = async () => {
    try {
      const response = await fetch(`/api/projects/${token}`, { cache: "no-store" });
      const data = await response.json();
      if (!response.ok) return;
      const nextProject = data.data as ProjectDetail;
      setProject(nextProject);
    } catch {
      // Best-effort background refresh; avoid surfacing noisy polling errors.
    }
  };

  const loadScheduledRuns = async (silent = false) => {
    try {
      if (!silent) {
        setScheduledRunsLoading(true);
      }
      const response = await fetch(`/api/scheduled-runs?project_token=${encodeURIComponent(token)}&limit=100`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to load scheduled runs");
      }
      setScheduledRuns((payload.data || []) as ScheduledRun[]);
    } catch {
      if (!silent) {
        setScheduledRuns([]);
      }
    } finally {
      if (!silent) {
        setScheduledRunsLoading(false);
      }
    }
  };

  useEffect(() => {
    void loadProject();
  }, [token]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.hidden) return;
      void pollProjectState();
    }, 30000);
    return () => window.clearInterval(interval);
  }, [token]);

  useEffect(() => {
    void loadScheduledRuns(false);
    const interval = window.setInterval(() => {
      void loadScheduledRuns(true);
    }, 30000);
    return () => window.clearInterval(interval);
  }, [token]);

  useEffect(() => {
    void loadResumeStatus(false);
    const interval = window.setInterval(() => {
      void loadResumeStatus(true);
    }, 30000);
    return () => window.clearInterval(interval);
  }, [token]);

  const runProject = async () => {
    try {
      setAction("run");
      setError(null);
      setMessage(null);
      const response = await fetch("/api/projects/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to run project");
      }
      setMessage(`Run started: ${data.run_token}`);
      await loadProject();
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : "Failed to run project");
    } finally {
      setAction(null);
    }
  };

  const saveScheduledProjectRun = async () => {
    if (scheduleMode === "one_time" && !scheduleLocalTime) {
      setError("Please choose a local date and time before saving schedule.");
      return;
    }

    if (scheduleMode === "recurring" && !recurrenceLocalTime) {
      setError("Please choose a local time for recurring schedule.");
      return;
    }

    try {
      setScheduleSaving(true);
      setError(null);
      setMessage(null);

      const payload =
        scheduleMode === "one_time"
          ? {
              project_token: token,
              schedule_type: "one_time",
              scheduled_run_time: scheduleLocalTime,
              timezone: scheduleTimezone,
            }
          : {
              project_token: token,
              schedule_type: "recurring",
              timezone: scheduleTimezone,
              recurrence: {
                frequency: recurrenceFrequency,
                weekday: recurrenceFrequency === "weekly" ? recurrenceWeekday : undefined,
                day_of_month: recurrenceFrequency === "monthly" ? recurrenceDayOfMonth : undefined,
                local_time: recurrenceLocalTime,
              },
            };

      const response = await fetch("/api/schedule-run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const responsePayload = await response.json();

      if (!response.ok || !responsePayload.success) {
        throw new Error(responsePayload.error || "Failed to schedule project run");
      }

      const scheduleText =
        formatScheduledTimeLocal(responsePayload.schedule?.scheduled_run_time_local) ||
        formatScheduledTimeLocal(responsePayload.schedule?.scheduled_run_time_utc) ||
        scheduleLocalTime || recurrenceLocalTime;
      setMessage(
        scheduleMode === "one_time"
          ? `One-time schedule saved for ${scheduleText}.`
          : `Recurring schedule saved. Next run: ${scheduleText}.`
      );
      setSchedulePickerOpen(false);
      setScheduleLocalTime("");
      setScheduleMode("one_time");
      await loadScheduledRuns(true);
      await loadProject();
    } catch (scheduleError) {
      setError(scheduleError instanceof Error ? scheduleError.message : "Failed to schedule project run");
    } finally {
      setScheduleSaving(false);
    }
  };

  const refreshRunStatus = async ({ silent = false }: { silent?: boolean } = {}) => {
    if (!project?.last_run?.run_token) {
      if (!silent) {
        setError("No run token available to check.");
      }
      return;
    }
    try {
      if (!silent) {
        setAction("status");
        setError(null);
        setMessage(null);
      }
      const response = await fetch(`/api/runs/${project.last_run.run_token}`);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to check run status");
      }
      if (!silent) {
        setMessage(`Latest run status: ${data.run.status}`);
      }
      await loadProject();
    } catch (statusError) {
      if (!silent) {
        setError(statusError instanceof Error ? statusError.message : "Failed to check run status");
      }
    } finally {
      if (!silent) {
        setAction(null);
      }
    }
  };

  useEffect(() => {
    const runToken = project?.last_run?.run_token;
    const runStatus = String(project?.last_run?.status || "").toLowerCase();
    const shouldPoll = !!runToken && ["running", "queued", "initialized"].includes(runStatus);

    if (!shouldPoll) {
      return;
    }

    const interval = window.setInterval(() => {
      void refreshRunStatus({ silent: true });
    }, 30000);

    return () => window.clearInterval(interval);
  }, [project?.last_run?.run_token, project?.last_run?.status]);

  useEffect(() => {
    const runStatus = normalizeRunStatus(project?.last_run?.status);
    const runSettled = !ACTIVE_RUN_STATUSES.has(runStatus);
    const isTransientStartMessage =
      typeof message === "string" &&
      (message.startsWith("Run started:") || message.startsWith("Resume started:"));
    if (isTransientStartMessage && runSettled) {
      setMessage(null);
    }
  }, [project?.last_run?.status, message]);

  const cancelRun = async () => {
    if (!project?.last_run?.run_token) {
      return;
    }
    try {
      setAction("cancel");
      setError(null);
      setMessage(null);
      const response = await fetch(`/api/runs/${project.last_run.run_token}/cancel`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to cancel run");
      }
      setMessage("Run cancelled.");
      await loadProject();
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "Failed to cancel run");
    } finally {
      setAction(null);
    }
  };

  const resumeProject = async () => {
    if (!resumeStatus?.resumable) {
      setError("Project is not currently resumable.");
      return;
    }
    const activeRun = ACTIVE_RUN_STATUSES.has(normalizeRunStatus(project?.last_run?.status));
    if (activeRun) {
      setError("Project already has an active run.");
      return;
    }
    try {
      setAction("resume");
      setError(null);
      setMessage(null);
      const response = await fetch(`/api/projects/${token}/resume`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || payload.message || "Failed to resume project");
      }
      setMessage(`Resume started: ${payload.run_token || "run created"}`);
      if (payload.run_token) {
        setProject((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            last_run: {
              run_token: String(payload.run_token),
              status: "running",
              updated_at: new Date().toISOString(),
            },
          };
        });
      }
      await loadProject();
      // Resume creation can be eventually consistent; do quick follow-up refreshes.
      window.setTimeout(() => {
        void loadProject();
      }, 1200);
      window.setTimeout(() => {
        void loadProject();
      }, 3000);
      await loadResumeStatus(true);
    } catch (resumeError) {
      setError(resumeError instanceof Error ? resumeError.message : "Failed to resume project");
    } finally {
      setAction(null);
    }
  };

  const loadStoredData = async () => {
    if (!project?.id) {
      setStoredDataError("Project ID is missing. Refresh and try again.");
      return;
    }
    try {
      setAction("data");
      setStoredDataRequested(true);
      setStoredDataError(null);
      setError(null);

      const [dataResponse, summaryResponse] = await Promise.all([
        fetch(`/api/data?token=${token}&limit=all&latest_only=1`),
        fetch(`/api/products/${project.id}/cumulative-stats`),
      ]);

      const dataPayload = await dataResponse.json();
      const summaryPayload = await summaryResponse.json();

      if (!dataResponse.ok) {
        throw new Error(dataPayload.error || "Failed to load stored data");
      }
      if (!summaryResponse.ok) {
        throw new Error(summaryPayload.error || "Failed to load summary statistics");
      }

      const rows = (dataPayload.data || []) as StoredDataRow[];
      const currentSessionCumulativeId = dataPayload.current_cumulative_session?.project_run_cumulative_id as string | undefined;
      const derivedFromRows = rows
        .filter((row) => !!row.project_run_cumulative_id)
        .map((row) => ({
          project_run_cumulative_id: String(row.project_run_cumulative_id),
          extraction_date: row.extraction_date || "",
        }))
        .sort((a, b) => b.extraction_date.localeCompare(a.extraction_date))[0]?.project_run_cumulative_id;

      const resolvedCumulativeId = currentSessionCumulativeId || derivedFromRows || null;
      setLatestCumulativeId(resolvedCumulativeId);
      setSelectedCumulativeId(resolvedCumulativeId);
      setPreviewData(rows);
      setCumulativeSummaries((summaryPayload.groups || []) as CumulativeSummaryGroup[]);
      setMessage(`Loaded ${dataPayload.count || 0} stored records from Snowflake.`);
    } catch (previewError) {
      const messageText = previewError instanceof Error ? previewError.message : "Failed to load stored data";
      setStoredDataError(messageText);
      setError(messageText);
    } finally {
      setAction(null);
    }
  };

  const loadStoredDataForCumulative = async (cumulativeId: string) => {
    if (!project?.id) {
      setStoredDataError("Project ID is missing. Refresh and try again.");
      return;
    }
    try {
      setAction("data");
      setStoredDataRequested(true);
      setStoredDataError(null);
      setError(null);

      const response = await fetch(`/api/data?token=${token}&limit=all&latest_only=0&cumulative_session=${encodeURIComponent(cumulativeId)}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load cumulative session data");
      }

      setSelectedCumulativeId(cumulativeId);
      setPreviewData((payload.data || []) as StoredDataRow[]);
      setMessage(`Loaded ${payload.count || 0} records for the selected extraction window.`);
    } catch (sessionError) {
      const messageText = sessionError instanceof Error ? sessionError.message : "Failed to load cumulative session data";
      setStoredDataError(messageText);
      setError(messageText);
    } finally {
      setAction(null);
    }
  };

  const selectedCumulativeRows = useMemo(() => {
    if (!previewData.length) {
      return [] as StoredDataRow[];
    }
    const activeCumulativeId = selectedCumulativeId || latestCumulativeId;
    if (!activeCumulativeId) {
      return previewData;
    }
    return previewData.filter((row) => row.project_run_cumulative_id === activeCumulativeId);
  }, [previewData, latestCumulativeId, selectedCumulativeId]);

  const sessionOptions = useMemo(() => {
    return cumulativeSummaries.map((group) => {
      const labelDate = formatDisplayDateTime(group.last_extraction_date || group.first_extraction_date);
      return {
        value: group.project_run_cumulative_id,
        label: labelDate,
      };
    });
  }, [cumulativeSummaries]);

  const selectedOptionLabel = useMemo(() => {
    const active = selectedCumulativeId || latestCumulativeId;
    if (!active) {
      return null;
    }
    return sessionOptions.find((option) => option.value === active)?.label || null;
  }, [selectedCumulativeId, latestCumulativeId, sessionOptions]);

  const selectedRunId = useMemo(() => {
    const tokens = selectedCumulativeRows
      .map((row) => String(row.run_token || "").trim())
      .filter((row) => !!row);
    if (tokens.length > 0) {
      return tokens[0];
    }
    return project?.last_run?.run_token || null;
  }, [selectedCumulativeRows, project?.last_run?.run_token]);

  const buildExportHref = (format: "csv" | "json") => {
    const params = new URLSearchParams({ token, format });
    if (selectedCumulativeId) {
      params.set("cumulative_session", selectedCumulativeId);
      params.set("latest_only", "0");
    } else {
      params.set("latest_only", "1");
    }
    return `/api/export?${params.toString()}`;
  };

  const displayedPreviewData =
    previewRowLimit === "all" ? selectedCumulativeRows : selectedCumulativeRows.slice(0, Number.parseInt(previewRowLimit, 10));

  const uniqueStats = useMemo(() => {
    const normalize = (value: unknown) => String(value ?? "").trim();
    const productNames = new Set<string>();
    const partNumbers = new Set<string>();
    const productUrls = new Set<string>();
    const pageNumbers = new Set<string>();
    const salePrices = new Set<string>();

    for (const row of selectedCumulativeRows) {
      const name = normalize(row.name);
      if (name) productNames.add(name);

      const part = normalize(row.part_number);
      if (part) partNumbers.add(part);

      const url = normalize(row.product_url);
      if (url) productUrls.add(url);

      const page = normalize(row.page_number);
      if (page) pageNumbers.add(page);

      const price = normalize(row.sale_price);
      if (price) salePrices.add(price);
    }

    return {
      uniqueProductNames: productNames.size,
      uniquePartNumbers: partNumbers.size,
      uniqueProductUrls: productUrls.size,
      uniquePageNumbers: pageNumbers.size,
      uniqueSalePrices: salePrices.size,
    };
  }, [selectedCumulativeRows]);

  const pageFrequency = useMemo(() => {
    const counts = new Map<number, number>();
    for (const row of selectedCumulativeRows) {
      const pageNumber = typeof row.page_number === "number" ? row.page_number : Number(row.page_number);
      if (!Number.isFinite(pageNumber)) continue;
      const normalizedPage = Math.trunc(pageNumber);
      counts.set(normalizedPage, (counts.get(normalizedPage) || 0) + 1);
    }

    return Array.from(counts.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([pageNumber, rowCount]) => ({ pageNumber, rowCount }));
  }, [selectedCumulativeRows]);

  const dataQualityStats = useMemo(() => {
    const normalize = (value: unknown) => String(value ?? "").trim();
    const normalizeKey = (value: unknown) => normalize(value).toLowerCase();

    const totalRows = selectedCumulativeRows.length;
    if (totalRows === 0) {
      return {
        totalRows: 0,
        missingName: 0,
        missingPartNumber: 0,
        missingProductUrl: 0,
        missingPageNumber: 0,
        invalidPrice: 0,
        inconsistentCountryOrBrand: 0,
        dominantCountry: null as string | null,
        dominantBrand: null as string | null,
        nullPercentages: {
          name: 0,
          part_number: 0,
          product_url: 0,
          page_number: 0,
          sale_price: 0,
          country: 0,
          brand: 0,
        },
      };
    }

    let missingName = 0;
    let missingPartNumber = 0;
    let missingProductUrl = 0;
    let missingPageNumber = 0;
    let invalidPrice = 0;
    let nullCountry = 0;
    let nullBrand = 0;

    const countryCounts = new Map<string, number>();
    const brandCounts = new Map<string, number>();

    for (const row of selectedCumulativeRows) {
      const name = normalize(row.name);
      const part = normalize(row.part_number);
      const url = normalize(row.product_url);
      const pageRaw = normalize(row.page_number);
      const priceRaw = normalize(row.sale_price);
      const country = normalize(row.country);
      const brand = normalize(row.brand);

      if (!name) missingName += 1;
      if (!part) missingPartNumber += 1;
      if (!url) missingProductUrl += 1;

      const parsedPage = Number(pageRaw);
      const pageInvalid = !pageRaw || !Number.isFinite(parsedPage) || !Number.isInteger(parsedPage) || parsedPage <= 0;
      if (pageInvalid) missingPageNumber += 1;

      const parsedPrice = Number(priceRaw.replace(/,/g, ""));
      const priceInvalid = !priceRaw || !Number.isFinite(parsedPrice) || parsedPrice < 0;
      if (priceInvalid) invalidPrice += 1;

      if (!country) {
        nullCountry += 1;
      } else {
        const key = normalizeKey(country);
        countryCounts.set(key, (countryCounts.get(key) || 0) + 1);
      }

      if (!brand) {
        nullBrand += 1;
      } else {
        const key = normalizeKey(brand);
        brandCounts.set(key, (brandCounts.get(key) || 0) + 1);
      }
    }

    const getDominantKey = (counts: Map<string, number>): string | null => {
      let bestKey: string | null = null;
      let bestCount = -1;
      for (const [key, count] of counts.entries()) {
        if (count > bestCount) {
          bestKey = key;
          bestCount = count;
        }
      }
      return bestKey;
    };

    const dominantCountryKey = getDominantKey(countryCounts);
    const dominantBrandKey = getDominantKey(brandCounts);

    // Inconsistency rule: if a row has a non-empty country/brand that differs
    // from the dominant non-empty value in the selected cumulative session,
    // count that row as inconsistent.
    let inconsistentCountryOrBrand = 0;
    for (const row of selectedCumulativeRows) {
      const countryKey = normalizeKey(row.country);
      const brandKey = normalizeKey(row.brand);
      const countryMismatch = !!countryKey && !!dominantCountryKey && countryKey !== dominantCountryKey;
      const brandMismatch = !!brandKey && !!dominantBrandKey && brandKey !== dominantBrandKey;
      if (countryMismatch || brandMismatch) {
        inconsistentCountryOrBrand += 1;
      }
    }

    const pct = (count: number) => Number(((count / totalRows) * 100).toFixed(1));
    return {
      totalRows,
      missingName,
      missingPartNumber,
      missingProductUrl,
      missingPageNumber,
      invalidPrice,
      inconsistentCountryOrBrand,
      dominantCountry: dominantCountryKey,
      dominantBrand: dominantBrandKey,
      nullPercentages: {
        name: pct(missingName),
        part_number: pct(missingPartNumber),
        product_url: pct(missingProductUrl),
        page_number: pct(missingPageNumber),
        sale_price: pct(invalidPrice),
        country: pct(nullCountry),
        brand: pct(nullBrand),
      },
    };
  }, [selectedCumulativeRows]);

  if (loading) {
    return (
      <main className="app-page flex-1 overflow-y-auto">
        <div className="app-page-header px-8 py-6">
          <div className="inline-flex items-center gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2.5 py-1.5">
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
            <span className="app-copy text-xs font-medium">Loading, please wait…</span>
          </div>
          <div className="h-4 w-24 animate-pulse rounded bg-[var(--bg-elevated)]" />
          <div className="mt-4 h-8 w-72 animate-pulse rounded bg-[var(--bg-elevated)]" />
          <div className="mt-3 flex gap-2">
            <div className="h-6 w-20 animate-pulse rounded-full bg-[var(--bg-elevated)]" />
            <div className="h-6 w-24 animate-pulse rounded-full bg-[var(--bg-elevated)]" />
            <div className="h-6 w-24 animate-pulse rounded-full bg-[var(--bg-elevated)]" />
          </div>
        </div>

        <div className="mx-auto max-w-[1280px] space-y-5 px-8 py-6">
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)]">
            <div className="app-surface-elevated rounded-lg p-4">
              <div className="h-4 w-20 animate-pulse rounded bg-[var(--bg-elevated)]" />
              <div className="mt-3 flex flex-wrap gap-2">
                <div className="h-9 w-28 animate-pulse rounded bg-[var(--bg-elevated)]" />
                <div className="h-9 w-32 animate-pulse rounded bg-[var(--bg-elevated)]" />
                <div className="h-9 w-28 animate-pulse rounded bg-[var(--bg-elevated)]" />
              </div>
            </div>
            <div className="app-surface-elevated rounded-lg p-4">
              <div className="h-4 w-28 animate-pulse rounded bg-[var(--bg-elevated)]" />
              <div className="mt-3 space-y-2">
                <div className="h-8 w-full animate-pulse rounded bg-[var(--bg-elevated)]" />
                <div className="h-8 w-full animate-pulse rounded bg-[var(--bg-elevated)]" />
                <div className="h-8 w-full animate-pulse rounded bg-[var(--bg-elevated)]" />
              </div>
            </div>
          </div>

          <div className="saas-card space-y-3">
            <div className="h-5 w-40 animate-pulse rounded bg-[var(--bg-elevated)]" />
            <div className="h-40 w-full animate-pulse rounded-lg bg-[var(--bg-elevated)]" />
          </div>

          <div className="saas-card space-y-3">
            <div className="h-5 w-32 animate-pulse rounded bg-[var(--bg-elevated)]" />
            <div className="h-56 w-full animate-pulse rounded-lg bg-[var(--bg-elevated)]" />
          </div>
        </div>
      </main>
    );
  }

  const runStatus = project?.last_run?.status;
  const normalizedRunStatus = normalizeRunStatus(runStatus);
  const hasActiveRun = ACTIVE_RUN_STATUSES.has(normalizedRunStatus);
  const automationInProgress = Boolean(project?.automation_state?.in_automated_progression);
  const shouldUseResumeFlow = Boolean(resumeStatus?.resumable) && !Boolean(resumeStatus?.project_complete);
  const statusBadge = !runStatus || runStatus === "idle"
    ? <span className="badge-idle"><span className="status-dot idle" />Idle</span>
    : normalizedRunStatus === "running"
    ? <span className="badge-running"><span className="status-dot running animate-pulse" />Running</span>
    : COMPLETED_RUN_STATUSES.has(normalizedRunStatus)
    ? <span className="badge-complete"><span className="status-dot complete" />Complete</span>
    : <span className="badge-idle">{runStatus}</span>;

  const completion = project?.completion_progress;
  const confirmedPages = Math.max(0, Number(completion?.confirmed_pages || 0));
  const livePages = Math.max(0, Number(completion?.live_pages || 0));
  const displayedProgressPages = Math.max(0, Number(completion?.displayed_progress_pages || 0));
  const numeratorPagesScraped = Math.max(0, Number(completion?.numerator_pages_scraped || 0));
  const resumeMaxPageScraped = Math.max(0, Number(resumeStatus?.max_page_scraped || 0));
  const lastRunPagesScraped = Math.max(0, Number(project?.last_run?.pages_scraped || 0));
  // Keep progress monotonic across payload timing differences between completion and live resume updates.
  const pagesScraped = Math.max(
    displayedProgressPages,
    numeratorPagesScraped,
    confirmedPages + livePages,
    confirmedPages,
    resumeMaxPageScraped,
    lastRunPagesScraped
  );
  const denominator = Math.max(0, Number(completion?.denominator || 0));
  const progressPercent = denominator > 0
    ? Math.max(0, Math.min(100, Math.round((pagesScraped / denominator) * 100)))
    : Math.max(0, Math.min(100, Number(completion?.progress_percent || 0)));
  const progressStatus = completion?.status || "no_run_progress";
  const websiteType = completion?.website_type || project?.metadata?.website_type || null;
  const projectLooksComplete = denominator > 0 && pagesScraped >= denominator;
  const resumeHasNoActiveSessionMessage =
    typeof resumeStatus?.message === "string" &&
    resumeStatus.message.toLowerCase().includes("no active cumulative run session");
  const resumeUiComplete = Boolean(resumeStatus?.project_complete) || (resumeHasNoActiveSessionMessage && projectLooksComplete);
  const resumeUiTitle = resumeUiComplete ? "Complete" : resumeStatus?.resumable ? "Resumable" : "Not Resumable";
  const resumeUiMessage =
    resumeUiComplete && resumeHasNoActiveSessionMessage
      ? `Project appears complete (${pagesScraped}/${denominator} pages). Start a new manual Run if you want a fresh extraction session.`
      : (resumeStatus?.message || "");

  const progressStatusLabel = (() => {
    if (progressStatus === "complete") return "Complete";
    if (progressStatus === "live_in_progress") return "Live";
    if (progressStatus === "in_progress_no_active_run") return "No Active Run";
    if (progressStatus === "in_progress") return "In Progress";
    if (progressStatus === "inconsistent_data") return "Inconsistent Data";
    if (progressStatus === "invalid_denominator") return "Missing Denominator";
    if (progressStatus === "no_run_progress") return "No Run Progress Yet";
    return "Website Type Required";
  })();
  const showFullscreenActionLoader = action === "data";

  return (
    <main className="app-page relative flex-1 overflow-y-auto">
      {showFullscreenActionLoader && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[1px]">
          <div className="app-surface flex items-center gap-3 rounded-xl px-5 py-4 shadow-lg">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
            <span className="app-copy text-sm">Loading stored data…</span>
          </div>
        </div>
      )}

      {/* ── Dark page header ────────────────────────────────── */}
      <div className="app-page-header px-8 py-6">
        <Link href="/" className="app-copy inline-flex items-center gap-1.5 text-xs font-medium transition hover:text-[var(--accent-primary)]">
          <ArrowLeft className="h-3.5 w-3.5" />
          Projects
        </Link>
        <div className="mt-4 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="section-label">Workflow</p>
            <h1 className="app-title mt-1 text-[28px] font-semibold tracking-[-0.02em]">{project?.title || token}</h1>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              {statusBadge}
              {project?.metadata?.region && <span className="app-badge app-badge-neutral">Region: {project.metadata.region}</span>}
              {project?.metadata?.brand  && <span className="app-badge app-badge-neutral">Brand: {project.metadata.brand}</span>}
              {project?.metadata?.website_type && <span className="app-badge app-badge-neutral">Type: {project.metadata.website_type}</span>}
              {project?.metadata?.total_pages && <span className="app-badge app-badge-neutral">Pages: {project.metadata.total_pages}</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-5">

        {/* ── Top Header Progress ─────────────────────────────── */}
        <div className="app-surface rounded-xl px-5 py-4">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="app-title text-sm font-semibold">Project Completion Progress</p>
            <span className="app-copy text-xs font-medium">{progressStatusLabel}</span>
          </div>
          <div className="h-3 w-full overflow-hidden rounded-full bg-[var(--bg-elevated)]">
            <div
              className={`h-full rounded-full transition-[width] duration-500 ease-out ${completion?.inconsistent ? "bg-[#F59E0B]" : "bg-[#3B82F6]"}`}
              style={{ width: denominator > 0 ? `${progressPercent}%` : "0%" }}
              role="progressbar"
              aria-valuenow={progressPercent}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label="Project completion progress"
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
            {denominator > 0 ? (
              <>
                <span className="app-copy font-mono">
                  {pagesScraped} / {denominator}{" "}
                  {websiteType === "Collective" ? "(pages+products)" : "pages"}
                </span>
                <span className="app-title font-semibold">{progressPercent}% complete</span>
              </>
            ) : (
              <>
                <span className="app-copy-weak font-mono">
                  {progressStatus === "invalid_website_type"
                    ? "Target not configured — set website type in metadata"
                    : "Target not configured — set total_pages in metadata"}
                </span>
                <span className="app-copy-weak font-semibold">—</span>
              </>
            )}
          </div>
          {denominator > 0 && (confirmedPages > 0 || livePages > 0) && (
            <p className="app-copy mt-2 text-xs">
              {confirmedPages} confirmed
              {livePages > 0 ? ` + ${livePages} live` : " + 0 live"}
            </p>
          )}
          {completion?.inconsistent && (
            <p className="mt-2 text-xs text-[#B45309]">
              Hybrid progress exceeds target denominator. Display is clamped to 100%.
            </p>
          )}
          {completion && progressStatus === "invalid_website_type" && (
            <p className="mt-2 text-xs text-[#B45309]">
              Set metadata website_type to Collective or Individual to enable progress calculation.
            </p>
          )}
          <div className="app-surface-elevated mt-3 rounded-md px-3 py-2 text-xs app-copy">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span>
                Automation: {project?.automation_state?.automation_enabled ? "Enabled" : "Disabled"}
                {project?.automation_state?.scheduler_enabled ? " (scheduler active)" : " (scheduler off)"}
              </span>
              <span>
                State: {project?.automation_state?.in_automated_progression ? "Auto progression active" : "Idle"}
              </span>
            </div>
            {project?.automation_state?.latest_ingestion?.run_token && (
              <div className="app-copy mt-1 break-all font-mono text-[11px]">
                Last ingest: {project.automation_state.latest_ingestion.status || "unknown"} | run {project.automation_state.latest_ingestion.run_token}
              </div>
            )}
          </div>
        </div>

        {/* ── Alert ───────────────────────────────────────────── */}
        {(error || message) && (
          <div className={`app-alert rounded-lg px-4 py-3 text-sm ${error ? "app-alert-error" : "app-alert-success"}`}>
            {error || message}
          </div>
        )}

        {/* ── Run Controls ────────────────────────────────────── */}
        <div className="saas-card space-y-5">
          <div>
            <h2 className="app-title text-base font-bold">Run Controls</h2>
            <p className="app-copy mt-1 text-sm">Each action is explicit — nothing keeps running in the background.</p>
          </div>

          {/* 3-column action grid */}
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(280px,1fr)] lg:items-stretch">
            {/* Primary actions */}
            <div className="app-surface-elevated flex flex-col gap-3 rounded-lg p-4">
              <span className="section-label">Actions</span>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  onClick={() => void runProject()}
                  disabled={action !== null || hasActiveRun || automationInProgress || shouldUseResumeFlow}
                  className="btn-primary h-9 px-4 text-sm"
                >
                  <Play className="h-3.5 w-3.5" />
                  {action === "run" ? "Starting…" : hasActiveRun ? "Running…" : "Run Project"}
                </button>
                <button
                  onClick={() => {
                    setSchedulePickerOpen((current) => {
                      const next = !current;
                      if (next) {
                        if (!scheduleLocalTime) {
                          setScheduleLocalTime(getLocalDateTimeInputValue(5));
                        }
                        if (!scheduleTimezone) {
                          setScheduleTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
                        }
                      }
                      return next;
                    });
                  }}
                  disabled={scheduleSaving}
                  className="btn-secondary h-9 px-4 text-sm"
                >
                  {schedulePickerOpen ? "Close Scheduler" : "Schedule Project"}
                </button>
                <button onClick={() => void refreshRunStatus()} disabled={action !== null || !project?.last_run?.run_token} className="btn-secondary h-9 px-4 text-sm">
                  <RefreshCcw className="h-3.5 w-3.5" />
                  {action === "status" ? "Checking…" : "Check Run"}
                </button>
                <button onClick={() => void cancelRun()} disabled={action !== null || project?.last_run?.status !== "running"} className="btn-danger h-9 px-4 text-sm">
                  <Square className="h-3.5 w-3.5" />
                  {action === "cancel" ? "Cancelling…" : "Cancel"}
                </button>
              </div>
              {shouldUseResumeFlow && (
                <p className="app-copy mt-1 text-xs">
                  This project has resumable progress. Use <span className="font-semibold">Resume Project</span>
                  {resumeStatus?.next_page_number ? ` to continue from page ${resumeStatus.next_page_number}.` : " to continue from the next page."}
                </p>
              )}
              {schedulePickerOpen && (
                <div className="app-surface mt-1 space-y-3 rounded-lg p-3">
                  <div className="grid gap-2 md:grid-cols-3">
                    <select
                      value={scheduleMode}
                      onChange={(event) => setScheduleMode(event.target.value as ScheduleMode)}
                      className="saas-select h-9 text-xs"
                    >
                      <option value="one_time">One time</option>
                      <option value="recurring">Recurring</option>
                    </select>
                    <select
                      value={scheduleTimezone}
                      onChange={(event) => setScheduleTimezone(event.target.value)}
                      className="saas-select h-9 text-xs"
                    >
                      {timezoneOptions.map((tz) => (
                        <option key={tz} value={tz}>
                          {tz}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => void saveScheduledProjectRun()}
                      disabled={scheduleSaving}
                      className="btn-primary h-9 px-4 text-sm disabled:opacity-50"
                    >
                      {scheduleSaving ? "Saving…" : "Save Schedule"}
                    </button>
                  </div>

                  {scheduleMode === "one_time" ? (
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                      <input
                        type="datetime-local"
                        value={scheduleLocalTime}
                        onChange={(event) => setScheduleLocalTime(event.target.value)}
                        min={getLocalDateTimeInputValue(0)}
                        className="saas-select h-9 min-w-[250px] text-xs"
                      />
                      <p className="app-copy text-xs">Runs once at the selected local date/time in {scheduleTimezone}.</p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="grid gap-2 md:grid-cols-4">
                        <span className="app-copy flex items-center text-xs">Every</span>
                        <select
                          value={recurrenceFrequency}
                          onChange={(event) => setRecurrenceFrequency(event.target.value as RecurrenceFrequency)}
                          className="saas-select h-9 text-xs"
                        >
                          <option value="daily">day</option>
                          <option value="weekly">week</option>
                          <option value="monthly">month</option>
                        </select>

                        {recurrenceFrequency === "weekly" ? (
                          <select
                            value={recurrenceWeekday}
                            onChange={(event) => setRecurrenceWeekday(Number(event.target.value))}
                            className="saas-select h-9 text-xs"
                          >
                            {WEEKDAY_OPTIONS.map((item) => (
                              <option key={item.value} value={item.value}>{item.label}</option>
                            ))}
                          </select>
                        ) : recurrenceFrequency === "monthly" ? (
                          <select
                            value={recurrenceDayOfMonth}
                            onChange={(event) => setRecurrenceDayOfMonth(Number(event.target.value))}
                            className="saas-select h-9 text-xs"
                          >
                            {DAY_OF_MONTH_OPTIONS.map((dom) => (
                              <option key={dom} value={dom}>Day {dom}</option>
                            ))}
                          </select>
                        ) : (
                          <span className="app-copy flex items-center text-xs">at</span>
                        )}

                        <input
                          type="time"
                          value={recurrenceLocalTime}
                          onChange={(event) => setRecurrenceLocalTime(event.target.value)}
                          className="saas-select h-9 text-xs"
                        />
                      </div>
                      <p className="app-copy text-xs">
                        Recurs in {scheduleTimezone}. Example: Every {recurrenceFrequency === "daily" ? "day" : recurrenceFrequency === "weekly" ? "week" : "month"} at {recurrenceLocalTime || "--:--"}.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Latest run status */}
            <div className="app-surface-elevated flex flex-col gap-2 rounded-lg p-4">
              <span className="section-label">Configuration</span>
              <div className="app-surface space-y-2 rounded-lg p-3 text-xs app-copy">
                {project?.last_run ? (
                  <>
                    <div className="flex items-center justify-between">
                      <span>Status</span>
                      <span className="app-title font-semibold">{project.last_run.status}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Pages</span>
                      <span className="app-title font-mono">{project.last_run.pages_scraped || 0} / {project.last_run.pages_requested || 0}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Data Ready</span>
                      <span className={project.last_run.data_ready ? "text-[var(--status-success-text)]" : "app-copy-weak"}>{project.last_run.data_ready ? "Yes" : "No"}</span>
                    </div>
                    <div className="border-t border-[var(--border-default)] pt-1">
                      <p className="app-copy-weak break-all font-mono text-[10px]">{project.last_run.run_token}</p>
                    </div>
                    {(project?.next_scheduled_run?.scheduled_run_time_local || project?.next_scheduled_run?.scheduled_run_time_utc) && (
                      <div className="border-t border-[var(--border-default)] pt-2">
                        <p className="app-copy text-[11px]">Next Scheduled Run</p>
                        <p className="app-title mt-1 text-xs font-semibold">
                          {formatScheduledTimeLocal(project.next_scheduled_run.scheduled_run_time_local) ||
                            formatScheduledTimeLocal(project.next_scheduled_run.scheduled_run_time_utc) ||
                            project.next_scheduled_run.scheduled_run_time_local ||
                            project.next_scheduled_run.scheduled_run_time_utc}
                        </p>
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <p className="app-copy-weak py-2 text-center">No runs yet</p>
                    {(project?.next_scheduled_run?.scheduled_run_time_local || project?.next_scheduled_run?.scheduled_run_time_utc) && (
                      <div className="border-t border-[var(--border-default)] pt-2">
                        <p className="app-copy text-[11px]">Next Scheduled Run</p>
                        <p className="app-title mt-1 text-xs font-semibold">
                          {formatScheduledTimeLocal(project.next_scheduled_run.scheduled_run_time_local) ||
                            formatScheduledTimeLocal(project.next_scheduled_run.scheduled_run_time_utc) ||
                            project.next_scheduled_run.scheduled_run_time_local ||
                            project.next_scheduled_run.scheduled_run_time_utc}
                        </p>
                      </div>
                    )}
                  </>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── Scheduled Runs ─────────────────────────────────── */}
        <div className="saas-card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="app-title text-base font-bold">Scheduled Runs</h2>
              <p className="app-copy mt-1 text-sm">Status tracking for scheduled, in-progress, completed, and failed runs.</p>
            </div>
            <button
              onClick={() => void loadScheduledRuns(false)}
              disabled={scheduledRunsLoading}
              className="btn-secondary h-9 px-4 text-sm disabled:opacity-40"
            >
              <RefreshCcw className="h-3.5 w-3.5" />
              {scheduledRunsLoading ? "Refreshing…" : "Refresh"}
            </button>
          </div>

          {scheduledRuns.length === 0 ? (
            <div className="app-surface-elevated rounded-lg px-4 py-3 text-sm app-copy">
              No scheduled runs yet for this project.
            </div>
          ) : (
            <div className="app-table-shell overflow-hidden rounded-lg">
              <div className="overflow-x-auto">
                <table className="saas-table">
                  <thead>
                    <tr>
                      <th>Project Name</th>
                      <th>Type</th>
                      <th>Rule</th>
                      <th>Next Run</th>
                      <th>Timezone</th>
                      <th>Status</th>
                      <th>Run Token</th>
                      <th>Last Updated</th>
                      <th>Error Message</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scheduledRuns.map((run) => {
                      const scheduledValue = run.scheduled_run_time || run.scheduled_run_time_local || run.scheduled_run_time_utc || null;
                      const lastUpdatedValue = run.last_updated || null;
                      return (
                        <tr key={run.id}>
                          <td>{run.project_name || project?.title || run.project_token}</td>
                          <td>{(run.schedule_type || "one_time") === "recurring" ? "Recurring" : "One time"}</td>
                          <td>{recurrenceSummary(run)}</td>
                          <td>{formatScheduledTimeLocal(scheduledValue) || "-"}</td>
                          <td>{run.timezone || "-"}</td>
                          <td>{run.status || "-"}</td>
                          <td className="font-mono text-[11px]">{run.run_token || "-"}</td>
                          <td>{formatScheduledTimeLocal(lastUpdatedValue) || "-"}</td>
                          <td>{run.error_message || "-"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* ── SQLite Data ──────────────────────────────────────── */}
        <div className="saas-card space-y-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h2 className="app-title text-base font-bold">Data Storage Pipeline</h2>
              <p className="app-copy mt-1 text-sm">Shows the latest ingested data currently available in the system.</p>
              {productStatsLoading && (
                <div className="mt-2 inline-flex items-center gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-elevated)] px-2.5 py-1.5">
                  <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--border-strong)] border-t-[var(--accent-primary)]" />
                  <span className="app-copy text-xs font-medium">Loading stats…</span>
                </div>
              )}
            </div>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-3 gap-3">
            {productStatsLoading ? (
              <>
                <div className="app-surface-elevated rounded-lg p-3">
                  <p className="section-label">Products</p>
                  <div className="mt-2 h-7 w-16 overflow-hidden rounded bg-[var(--bg-elevated)]">
                    <div className="h-full w-full animate-pulse bg-gradient-to-r from-transparent via-[var(--border-strong)]/60 to-transparent" />
                  </div>
                </div>
                <div className="app-surface-elevated rounded-lg p-3">
                  <p className="section-label">Max Page</p>
                  <div className="mt-2 h-7 w-16 overflow-hidden rounded bg-[var(--bg-elevated)]">
                    <div className="h-full w-full animate-pulse bg-gradient-to-r from-transparent via-[var(--border-strong)]/60 to-transparent" />
                  </div>
                </div>
                <div className="app-surface-elevated rounded-lg p-3">
                  <p className="section-label">Session Status</p>
                  <div className="mt-2 h-7 w-24 overflow-hidden rounded bg-[var(--bg-elevated)]">
                    <div className="h-full w-full animate-pulse bg-gradient-to-r from-transparent via-[var(--border-strong)]/60 to-transparent" />
                  </div>
                </div>
              </>
            ) : (
              [
                { label: "Products", val: productStats?.statistics?.total_products ?? 0 },
                { label: "Max Page", val: productStats?.statistics?.max_page_scraped ?? 0 },
                { label: "Session Status", val: project?.current_cumulative_session?.status ?? "none" },
              ].map(({ label, val }) => (
                <div key={label} className="app-surface-elevated rounded-lg p-3">
                  <p className="section-label">{label}</p>
                  <p className="app-title mt-1.5 font-mono text-lg font-semibold">{val}</p>
                </div>
              ))
            )}
          </div>

          {/* Metadata panel */}
          <details className="app-surface group rounded-lg">
            <summary className="app-copy select-none flex cursor-pointer items-center justify-between px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em]">
              Project Metadata
              <span className="app-copy-weak transition-transform group-open:rotate-90">›</span>
            </summary>
            <div className="border-t border-[var(--border-default)] px-4 pb-4 pt-3">
              <dl className="grid gap-3 text-sm md:grid-cols-2">
                {[
                  { label: "Brand",        val: project?.metadata?.brand },
                  { label: "Website Type", val: project?.metadata?.website_type },
                  { label: "Region",       val: project?.metadata?.region || project?.metadata?.country },
                  { label: "Target Pages", val: project?.metadata?.total_pages },
                  { label: "Total Products", val: project?.metadata?.total_products },
                  { label: "Latest Run ID", val: project?.last_run?.run_token, colSpan: true },
                  { label: "Runs In Current Session", val: project?.current_cumulative_session?.total_runs_in_session },
                ].map(({ label, val, colSpan }) => (
                  <div key={label} className={colSpan ? "md:col-span-2" : ""}>
                    <dt className="section-label">{label}</dt>
                    <dd className="app-title mt-1 break-all font-mono text-sm">{val ?? "-"}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </details>
        </div>

        {/* ── Resume Status ───────────────────────────────────── */}
        <div className="saas-card space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="app-title text-base font-bold">Resume Status</h2>
              <p className="app-copy mt-1 text-sm">Live read-only status from the resume-status service.</p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => void resumeProject()}
                disabled={
                  action !== null ||
                  !resumeStatus?.resumable ||
                  ACTIVE_RUN_STATUSES.has(normalizeRunStatus(project?.last_run?.status)) ||
                  automationInProgress
                }
                className="btn-primary h-9 px-4 text-sm disabled:opacity-40"
              >
                <Play className="h-3.5 w-3.5" />
                {action === "resume" ? "Resuming…" : "Resume Project"}
              </button>
              <button
                onClick={() => void loadResumeStatus(false)}
                disabled={resumeStatusLoading}
                className="btn-secondary h-9 px-4 text-sm disabled:opacity-40"
              >
                <RefreshCcw className="h-3.5 w-3.5" />
                {resumeStatusLoading ? "Refreshing…" : "Refresh Status"}
              </button>
            </div>
          </div>

          {resumeStatusError && (
            <div className="app-alert app-alert-error rounded-lg px-4 py-3 text-sm">
              {resumeStatusError}
            </div>
          )}

          {!resumeStatus && !resumeStatusError && (
            <div className="app-surface-elevated rounded-lg px-4 py-3 text-sm app-copy">
              Loading live resume status…
            </div>
          )}

          {resumeStatus && (
            <div className={`app-alert rounded-lg p-4 ${resumeUiComplete ? "app-alert-success" : resumeStatus.resumable ? "app-alert-info" : "app-alert-warning"}`}>
              <div className="flex items-start gap-3">
                {resumeUiComplete ? <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" /> : resumeStatus.resumable ? <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" /> : <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">
                    {resumeUiTitle}
                  </p>
                  <p className="mt-1 text-xs opacity-90">{resumeUiMessage}</p>
                  <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
                    <div><dt className="app-copy-weak">Current Run ID</dt><dd className="app-title font-mono">{selectedRunId || "-"}</dd></div>
                    <div><dt className="app-copy-weak">Automation State</dt><dd className="app-title">{project?.automation_state?.in_automated_progression ? "In Progress" : "Idle"}</dd></div>
                    <div><dt className="app-copy-weak">Max Page</dt><dd className="app-title font-mono">{resumeStatus.max_page_scraped ?? "-"}</dd></div>
                    <div><dt className="app-copy-weak">Total Pages</dt><dd className="app-title font-mono">{resumeStatus.total_pages ?? "-"}</dd></div>
                    <div><dt className="app-copy-weak">Next Page</dt><dd className="app-title font-mono">{resumeStatus.next_page_number ?? "-"}</dd></div>
                  </dl>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* ── Stored Data ──────────────────────────────────────── */}
        <div className="saas-card space-y-4">
          <div className="space-y-3">
            <div>
              <h2 className="app-title text-base font-bold">Stored Data</h2>
              <p className="app-copy mt-1 text-sm">Preview Scraped Data</p>
            </div>
            <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
              <div className="flex flex-wrap items-center gap-2 justify-start">
                <button onClick={() => void loadStoredData()} disabled={action !== null} className="btn-secondary h-9 px-4 text-sm">
                  <Database className="h-3.5 w-3.5" />
                  {action === "data" ? "Loading…" : "Load Data"}
                </button>
                <select
                  value={previewRowLimit}
                  onChange={(e) => setPreviewRowLimit(e.target.value as PreviewRowLimit)}
                  className="saas-select w-20 text-xs"
                >
                  <option value="10">10</option>
                  <option value="20">20</option>
                  <option value="50">50</option>
                  <option value="all">All</option>
                </select>
                <select
                  value={selectedCumulativeId || ""}
                  onChange={(e) => {
                    const next = e.target.value;
                    if (!next) return;
                    void loadStoredDataForCumulative(next);
                  }}
                  className="saas-select max-w-[320px] text-xs"
                  disabled={action === "data" || cumulativeSummaries.length === 0}
                  title={selectedOptionLabel || "Select extraction window"}
                >
                  {cumulativeSummaries.length === 0 ? (
                    <option value="">No extraction windows</option>
                  ) : (
                    sessionOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))
                  )}
                </select>
              </div>
              <div className="flex items-center gap-2 md:justify-end">
                <a href={buildExportHref("csv")} className="btn-secondary h-9 px-4 text-sm">
                  <Download className="h-3.5 w-3.5" />
                  CSV
                </a>
                <a href={buildExportHref("json")} className="btn-secondary h-9 px-4 text-sm">
                  <Download className="h-3.5 w-3.5" />
                  JSON
                </a>
              </div>
            </div>
          </div>

          {storedDataError && <p className="app-alert app-alert-error rounded-lg px-4 py-3 text-sm">{storedDataError}</p>}

          {storedDataRequested && selectedCumulativeRows.length > 0 && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
                {[
                  { label: "Product Names", val: uniqueStats.uniqueProductNames },
                  { label: "Part Numbers",  val: uniqueStats.uniquePartNumbers },
                  { label: "Product URLs",  val: uniqueStats.uniqueProductUrls },
                  { label: "Pages",         val: uniqueStats.uniquePageNumbers },
                  { label: "Sale Prices",   val: uniqueStats.uniqueSalePrices },
                ].map(({ label, val }) => (
                  <div key={label} className="app-surface rounded-lg p-3 text-center">
                    <p className="section-label">{label}</p>
                    <p className="app-title mt-1.5 text-2xl font-bold">{val}</p>
                  </div>
                ))}
              </div>

              <div className="app-surface rounded-lg p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="section-label">Data Quality Statistics (Selected Extraction Window)</p>
                  <span className="app-copy text-xs">Rows: {dataQualityStats.totalRows}</span>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {[
                    { label: "Missing Product Name", value: dataQualityStats.missingName },
                    { label: "Missing Part Number", value: dataQualityStats.missingPartNumber },
                    { label: "Missing Product URL", value: dataQualityStats.missingProductUrl },
                    { label: "Missing Page Number", value: dataQualityStats.missingPageNumber },
                    { label: "Invalid/Empty Price", value: dataQualityStats.invalidPrice },
                    { label: "Inconsistent Country/Brand", value: dataQualityStats.inconsistentCountryOrBrand },
                  ].map((item) => (
                    <div key={item.label} className="app-surface-elevated rounded-lg p-3">
                      <p className="app-copy text-[11px] font-semibold uppercase tracking-[0.08em]">{item.label}</p>
                      <p className="app-title mt-1 font-mono text-xl font-semibold">{item.value}</p>
                    </div>
                  ))}
                </div>

                <div className="app-table-shell mt-4 overflow-x-auto rounded-lg">
                  <table className="w-full text-left text-xs">
                    <thead className="app-table-head">
                      <tr>
                        <th className="px-3 py-2 font-semibold">Field</th>
                        <th className="px-3 py-2 font-semibold">Null/Invalid %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ["Product Name", dataQualityStats.nullPercentages.name],
                        ["Part Number", dataQualityStats.nullPercentages.part_number],
                        ["Product URL", dataQualityStats.nullPercentages.product_url],
                        ["Page Number", dataQualityStats.nullPercentages.page_number],
                        ["Sale Price", dataQualityStats.nullPercentages.sale_price],
                        ["Country", dataQualityStats.nullPercentages.country],
                        ["Brand", dataQualityStats.nullPercentages.brand],
                      ].map(([field, pctValue]) => (
                        <tr key={String(field)} className="app-table-row">
                          <td className="px-3 py-2 app-copy">{field}</td>
                          <td className="px-3 py-2 font-mono app-title">{String(pctValue)}%</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p className="app-copy mt-3 text-[11px]">
                  Dominant non-empty values used for consistency check: country={dataQualityStats.dominantCountry || "n/a"}, brand={dataQualityStats.dominantBrand || "n/a"}.
                </p>
              </div>
            </div>
          )}

          {storedDataRequested && previewData.length > 0 && (
            <div className="app-table-shell overflow-hidden rounded-lg">
              <div className="overflow-x-auto">
                <table className="saas-table">
                  <thead>
                    <tr>
                      {["Product Name","Part #","Brand","URL","Sale Price","Case Price","Currency","Country","Page","Date"].map(h => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {displayedPreviewData.map((row, i) => (
                      <tr key={i}>
                        <td className="app-title">{row.name ?? "-"}</td>
                        <td className="font-mono">{row.part_number ?? "-"}</td>
                        <td>{row.brand ?? "-"}</td>
                        <td className="app-link max-w-[160px] truncate" title={row.product_url ?? ""}>{row.product_url ?? "-"}</td>
                        <td className="font-mono">{row.sale_price ?? "-"}</td>
                        <td className="font-mono">{row.case_unit_price ?? "-"}</td>
                        <td>{row.currency ?? "-"}</td>
                        <td>{row.country ?? "-"}</td>
                        <td className="font-mono">{row.page_number ?? "-"}</td>
                        <td className="whitespace-nowrap text-[11px]">{row.extraction_date ?? "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {storedDataRequested && previewData.length === 0 && action !== "data" && !storedDataError && (
            <p className="app-copy-weak py-8 text-center text-sm">No stored data found for this project.</p>
          )}

          {!storedDataRequested && (
            <p className="app-copy-weak py-8 text-center text-sm">Click "Load Data" to preview stored rows.</p>
          )}

          {/* Per-page chart */}
          {storedDataRequested && pageFrequency.length > 0 && (
            <div className="app-surface rounded-lg p-4">
              <p className="section-label mb-4">Rows per Page (Selected Extraction Window)</p>
              <div className="app-chart-frame h-[340px] w-full rounded-lg p-3">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={pageFrequency} margin={{ top: 24, right: 16, left: 0, bottom: 18 }} barCategoryGap={14}>
                    <CartesianGrid stroke="var(--border-default)" strokeDasharray="4 4" vertical={false} />
                    <XAxis
                      dataKey="pageNumber"
                      tick={{ fill: "var(--text-secondary)", fontSize: 12, fontWeight: 600 }}
                      axisLine={{ stroke: "var(--border-strong)" }}
                      tickLine={{ stroke: "var(--border-strong)" }}
                      label={{ value: "Page Number", position: "insideBottom", offset: -8, fill: "var(--text-secondary)", fontSize: 11 }}
                    />
                    <YAxis
                      allowDecimals={false}
                      tick={{ fill: "var(--text-secondary)", fontSize: 12 }}
                      axisLine={{ stroke: "var(--border-strong)" }}
                      tickLine={{ stroke: "var(--border-strong)" }}
                      label={{ value: "Row Count", angle: -90, position: "insideLeft", fill: "var(--text-secondary)", fontSize: 11 }}
                    />
                    <Tooltip
                      cursor={{ fill: "rgba(59,130,246,0.08)" }}
                      contentStyle={{ borderRadius: 8, border: "1px solid var(--border-default)", backgroundColor: "var(--bg-surface)", fontSize: 12, color: "var(--text-primary)" }}
                      formatter={(value: number) => [`${value} rows`, "Row Count"]}
                      labelFormatter={(label: string | number) => `Page ${label}`}
                    />
                    <Bar dataKey="rowCount" fill="#2563EB" stroke="#1D4ED8" strokeWidth={1} radius={[6, 6, 0, 0]} maxBarSize={40}>
                      <LabelList dataKey="rowCount" position="top" fill="var(--text-primary)" fontSize={11} />
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

        </div>

      </div>
    </main>
  );
}
