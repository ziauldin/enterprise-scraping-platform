"use client";

import { useEffect, useState, useRef } from "react";
import {
  Upload,
  Download,
  CheckCircle,
  AlertCircle,
  Clock,
  Eye,
  EyeOff,
} from "lucide-react";


interface ImportResult {
  batch_id?: number;
  file_name?: string;
  stats?: {
    total_records: number;
    imported: number;
    skipped: number;
    errors: Array<{
      row: number;
      error: string;
      personal_id: string;
    }>;
  };
  success: boolean;
  error?: string;
}

interface ImportHistory {
  id: number;
  file_name: string;
  record_count: number;
  status: string;
  upload_date: string;
}

const TEMPLATE_HEADERS = [
  "Personal Project ID",
  "Project ID (ParseHub)",
  "Project_name",
  "Last_run_data",
  "Create_date",
  "update_date",
  "Region",
  "Country",
  "Brand",
  "Website_url",
  "Total_pages",
  "Total_products",
  "Current_page_scraped",
  "current_product_scraped",
  "next_page_url",
];

export default function ImportMetadataPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [importHistory, setImportHistory] = useState<ImportHistory[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    fetchImportHistory();
  }, []);

  const fetchImportHistory = async () => {
    try {
      console.log("[Import] Fetching import history...");
      
      const response = await fetch("/api/metadata/import-history");

      console.log("[Import] Import history response status:", response.status);

      if (response.ok) {
        const data = await response.json();
        console.log("[Import] Successfully fetched import history -", data.count || 0, "batches");
        setImportHistory(data.batches || []);
      } else {
        const errorData = await response.json().catch(() => ({}));
        console.error("[Import] Failed to fetch history:", response.status, errorData);
      }
    } catch (err) {
      console.error("[Import] Error fetching history:", err);
    }
  };

  const handleDrag = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const droppedFile = e.dataTransfer.files[0];
      if (droppedFile.name.endsWith(".xlsx") || droppedFile.name.endsWith(".xls")) {
        setFile(droppedFile);
        setError(null);
      } else {
        setError("Please upload an Excel file (.xlsx or .xls)");
      }
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selectedFile = e.target.files[0];
      if (selectedFile.name.endsWith(".xlsx") || selectedFile.name.endsWith(".xls")) {
        setFile(selectedFile);
        setError(null);
      } else {
        setError("Please upload an Excel file (.xlsx or .xls)");
      }
    }
  };

  const downloadTemplate = () => {
    const csv = TEMPLATE_HEADERS.join(",") + "\n";
    const element = document.createElement("a");
    element.setAttribute(
      "href",
      "data:text/csv;charset=utf-8," + encodeURIComponent(csv)
    );
    element.setAttribute("download", "metadata_template.csv");
    element.style.display = "none";
    document.body.appendChild(element);
    element.click();
    document.body.removeChild(element);
  };

  const handleImport = async () => {
    if (!file) {
      setError("Please select a file first");
      console.warn("[Import] No file selected");
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      console.log("[Import] Starting import for file:", file.name, "Size:", file.size, "bytes");
      
      const formData = new FormData();
      formData.append("file", file);
      formData.append("uploaded_by", "web_ui");

      const response = await fetch("/api/metadata/import", {
        method: "POST",
        body: formData,
      });

      console.log("[Import] Response status:", response.status, response.statusText);

      const data: ImportResult = await response.json();
      console.log("[Import] Response data:", data);

      if (response.ok && data.success) {
        console.log("[Import] Successfully imported", data.stats?.imported, "records");
        setResult(data);
        setFile(null);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        await fetchImportHistory();
      } else {
        const errorMsg = data.error || "Import failed";
        console.error("[Import] Import failed:", errorMsg, data);
        setError(errorMsg);
        setResult(data);
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err);
      console.error("[Import] Error:", errorMsg, err);
      setError(errorMsg);
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setFile(null);
    setResult(null);
    setError(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <main className="app-page flex-1 overflow-y-auto">

      {/* ── Top bar ─────────────────────────────────────────── */}
      <div className="app-page-header px-8 py-6">
        <p className="section-label">Data Management</p>
        <div className="mt-1 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="app-title text-[28px] font-semibold tracking-[-0.02em]">Import Metadata</h1>
          <button onClick={downloadTemplate} className="btn-secondary h-9 px-4 text-sm shrink-0">
            <Download className="h-3.5 w-3.5" />
            Download Template
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-5">

        {/* ── Alert ──────────────────────────────────────────── */}
        {error && (
          <div className="app-alert app-alert-error flex items-start gap-3 rounded-lg px-4 py-3 text-sm">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="font-semibold">Error</p>
              <p className="mt-0.5 opacity-80">{error}</p>
            </div>
          </div>
        )}

        {result?.success && (
          <div className="app-alert app-alert-success flex items-start gap-3 rounded-lg px-4 py-3 text-sm">
            <CheckCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="flex-1">
              <p className="font-semibold">Import Successful</p>
              <p className="mt-0.5 opacity-80">{result.stats?.imported} records imported, {result.stats?.skipped} skipped</p>
              {result.stats?.errors && result.stats.errors.length > 0 && (
                <details className="mt-2 text-xs opacity-80">
                  <summary className="cursor-pointer">View errors ({result.stats.errors.length})</summary>
                  <div className="mt-1 space-y-1">
                    {result.stats.errors.map((err, idx) => (
                      <p key={idx}>Row {err.row}: {err.error}</p>
                    ))}
                  </div>
                </details>
              )}
            </div>
            <button onClick={resetForm} className="btn-ghost h-8 px-3 text-xs shrink-0">Import Another</button>
          </div>
        )}

        <div className="grid gap-5 lg:grid-cols-3">
          {/* ── Upload section ─────────────────────────────── */}
          <div className="lg:col-span-2 saas-card space-y-5">
            <div>
              <h2 className="app-title text-base font-semibold">Upload File</h2>
              <p className="app-copy mt-1 text-sm">Drag and drop an Excel file or click to browse. Supports .xlsx and .xls.</p>
            </div>

            {/* Drop zone */}
            <div
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`relative cursor-pointer rounded-lg border-2 border-dashed px-8 py-14 text-center transition-all duration-200 ${
                dragActive
                  ? "border-[var(--accent-primary)] bg-[var(--status-info-bg)]"
                  : "border-[var(--border-default)] bg-[var(--bg-surface)] hover:border-[var(--accent-primary)]/50"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                onChange={handleFileChange}
                accept=".xlsx,.xls"
                className="hidden"
                disabled={loading}
                />

              <div className="flex flex-col items-center gap-4 pointer-events-none">
                <div className="app-surface-elevated flex h-12 w-12 items-center justify-center rounded-full">
                  <Upload className="h-5 w-5 text-[var(--accent-primary)]" />
                </div>
                <div>
                  <p className="app-title font-semibold">
                    {file ? file.name : "Drop your file here"}
                  </p>
                  <p className="app-copy mt-1 text-sm">or <span className="app-link">browse files</span></p>
                  <p className="app-copy-weak mt-2 text-xs">Supports .xlsx and .xls</p>
                </div>
              </div>
            </div>

            {/* File info */}
            {file && !result && (
              <div className="app-surface flex items-center justify-between rounded-lg px-4 py-3">
                <div>
                  <p className="app-title text-sm font-medium">{file.name}</p>
                  <p className="app-copy-weak text-xs">{(file.size / 1024).toFixed(1)} KB</p>
                </div>
                <button onClick={resetForm} disabled={loading} className="app-copy text-xs hover:text-[var(--status-danger-text)]">Remove</button>
              </div>
            )}

            {/* Actions */}
            {!result && (
              <div className="flex gap-3">
                <button
                  onClick={() => void handleImport()}
                  disabled={!file || loading}
                  className="btn-primary flex-1 h-10 text-sm"
                >
                  {loading ? (
                    <><div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />Importing…</>
                  ) : (
                    <><Upload className="h-3.5 w-3.5" />Import File</>
                  )}
                </button>
                {file && (
                  <button onClick={resetForm} disabled={loading} className="btn-secondary h-10 px-4 text-sm">Clear</button>
                )}
              </div>
            )}
          </div>

          {/* Info panel */}
          <div className="space-y-5">
            <div className="saas-card space-y-4">
              <h3 className="app-title text-sm font-semibold">Expected Format</h3>
              <div className="app-copy space-y-3 text-sm">
                <div>
                  <p className="section-label mb-1">Required</p>
                  <ul className="space-y-1 text-xs">
                    <li>• Personal Project ID</li>
                    <li>• Project_name</li>
                    <li>• Total_pages</li>
                  </ul>
                </div>
                <div className="border-t border-[var(--border-default)] pt-3">
                  <p className="section-label mb-1">Optional</p>
                  <ul className="space-y-1 text-xs">
                    <li>• Region, Country, Brand</li>
                    <li>• Website_url</li>
                    <li>• Total_products</li>
                    <li>• Current_page_scraped</li>
                  </ul>
                </div>
              </div>
            </div>

            {result?.stats && (
              <div className="saas-card space-y-3">
                <h3 className="app-title text-sm font-semibold">Import Results</h3>
                {[
                  { label: "Total", val: result.stats.total_records, color: "app-title" },
                  { label: "Imported", val: result.stats.imported, color: "text-[var(--status-success-text)]" },
                  { label: "Skipped",  val: result.stats.skipped,  color: "text-[var(--status-warning-text)]" },
                  ...(result.stats.errors.length ? [{ label: "Errors", val: result.stats.errors.length, color: "text-[var(--status-danger-text)]" }] : []),
                ].map(({ label, val, color }) => (
                  <div key={label} className="flex items-center justify-between text-sm">
                    <span className="app-copy">{label}</span>
                    <span className={`font-semibold font-mono ${color}`}>{val}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Import History */}
        <div className="saas-card space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="app-title text-base font-semibold">Import History</h2>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="btn-ghost h-8 px-3 text-xs"
            >
              {showHistory ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              {showHistory ? "Hide" : "Show"}
            </button>
          </div>

          {showHistory && (
            importHistory.length === 0 ? (
              <div className="app-copy-weak flex flex-col items-center gap-2 py-8">
                <Clock className="h-8 w-8 opacity-50" />
                <p className="text-sm">No import history yet</p>
              </div>
            ) : (
              <div className="app-table-shell overflow-hidden rounded-lg">
                <div className="overflow-x-auto">
                  <table className="saas-table">
                    <thead>
                      <tr>
                        <th>File Name</th>
                        <th className="text-center">Records</th>
                        <th>Status</th>
                        <th>Uploaded</th>
                      </tr>
                    </thead>
                    <tbody>
                      {importHistory.map((batch) => (
                        <tr key={batch.id}>
                          <td className="app-title">{batch.file_name}</td>
                          <td className="text-center font-mono">{batch.record_count}</td>
                          <td>
                            <span className={batch.status === "success" ? "badge-complete" : "badge-error"}>
                              {batch.status}
                            </span>
                          </td>
                          <td>{new Date(batch.upload_date).toLocaleDateString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          )}
        </div>

      </div>
    </main>
  );
}
