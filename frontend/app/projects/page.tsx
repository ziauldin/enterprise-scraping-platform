"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { FileUp, RefreshCcw } from "lucide-react";

interface MetadataRecord {
  id: number;
  personal_project_id: string;
  project_token?: string;
  project_name: string;
  region?: string;
  country?: string;
  brand?: string;
  website_url?: string;
  total_pages?: number;
  current_page_scraped?: number;
  current_product_scraped?: number;
  status?: string;
}

export default function ProjectsPage() {
  const [records, setRecords] = useState<MetadataRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadMetadata = async () => {
    try {
      setError(null);
      const response = await fetch("/api/metadata?limit=500");
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Failed to load metadata");
      }
      setRecords(data.records || []);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Failed to load metadata");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadMetadata();
  }, []);

  return (
    <main className="app-page flex-1 overflow-y-auto">

      {/* ── Top bar ─────────────────────────────────────────── */}
      <div className="app-page-header px-8 py-6">
        <p className="section-label">Metadata Registry</p>
        <div className="mt-1 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="app-title text-[28px] font-semibold tracking-[-0.02em]">Projects</h1>
          <div className="flex gap-2 shrink-0">
            <button onClick={() => void loadMetadata()} className="btn-secondary h-9 px-4 text-sm">
              <RefreshCcw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <Link href="/import-metadata" className="btn-primary h-9 px-4 text-sm">
              <FileUp className="h-3.5 w-3.5" />
              Import Metadata
            </Link>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-5">

        {error && <div className="app-alert app-alert-error rounded-lg px-4 py-3 text-sm">{error}</div>}

        {loading ? (
          <div className="app-copy flex items-center justify-center gap-2 py-12 text-sm">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
            Loading…
          </div>
        ) : (
          <div className="app-table-shell overflow-hidden rounded-lg">
            <div className="overflow-x-auto">
              <table className="saas-table">
                <thead>
                  <tr>
                    <th>Project</th>
                    <th>Brand</th>
                    <th>Region</th>
                    <th>Progress</th>
                    <th>Linked Flow</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record) => (
                    <tr key={record.id}>
                      <td>
                        <div className="app-title font-semibold">{record.project_name}</div>
                        <div className="app-copy-weak mt-0.5 font-mono text-xs">{record.personal_project_id}</div>
                      </td>
                      <td>{record.brand || "-"}</td>
                      <td>{record.region || record.country || "-"}</td>
                      <td className="font-mono">{record.current_page_scraped || 0} / {record.total_pages || 0}</td>
                      <td>
                        {record.project_token ? (
                          <Link href={`/projects/${record.project_token}`} className="app-link text-sm font-medium transition-colors">
                            Open Project
                          </Link>
                        ) : (
                          <span className="app-copy-weak text-sm">Not linked</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {records.length === 0 && (
              <div className="app-copy-weak py-10 text-center text-sm">No metadata records found.</div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
