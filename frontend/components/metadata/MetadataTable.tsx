"use client";

import { Trash2 } from "lucide-react";
import { MetadataRecord } from "@/components/metadata/types";

interface MetadataTableProps {
  rows: MetadataRecord[];
  savingRowId: string | null;
  deletingRowId: string | null;
  onEdit: (row: MetadataRecord) => void;
  onDelete: (row: MetadataRecord) => void;
  highlightedRowId?: string | null;
}

export default function MetadataTable({ rows, savingRowId, deletingRowId, onEdit, onDelete, highlightedRowId = null }: MetadataTableProps) {
  if (rows.length === 0) {
    return (
      <div className="app-empty-state rounded-xl px-4 py-8 text-center app-copy-weak">
        No metadata records found for this filter.
      </div>
    );
  }

  return (
    <div className="app-table-shell overflow-x-auto rounded-xl">
      <table className="w-full border-collapse text-left text-sm">
        <thead className="app-table-head text-xs uppercase tracking-[0.2em]">
          <tr>
            <th className="px-3 py-3">Personal ID</th>
            <th className="px-3 py-3">Project Token</th>
            <th className="px-3 py-3">Project Name</th>
            <th className="px-3 py-3">Website Type</th>
            <th className="px-3 py-3">Region</th>
            <th className="px-3 py-3">Country</th>
            <th className="px-3 py-3">Brand</th>
            <th className="px-3 py-3">Totals</th>
            <th className="px-3 py-3">Updated</th>
            <th className="px-3 py-3">Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const rowId = row.personal_project_id;
            const isSaving = savingRowId === rowId;
            const isDeleting = deletingRowId === rowId;
            const isHighlighted = highlightedRowId === rowId;
            const isBusy = isSaving || isDeleting;
            return (
              <tr key={rowId} className={`app-table-row transition ${isHighlighted ? "app-table-row-active" : ""}`}>
                <td className="px-3 py-3 font-mono text-xs app-link">{row.personal_project_id}</td>
                <td className="px-3 py-3 font-mono text-xs">{row.project_id_parsehub || "-"}</td>
                <td className="px-3 py-3">{row.project_name || "-"}</td>
                  <td className="px-3 py-3">{row.website_type || "-"}</td>
                <td className="px-3 py-3">{row.region || "-"}</td>
                <td className="px-3 py-3">{row.country || "-"}</td>
                <td className="px-3 py-3">{row.brand || "-"}</td>
                <td className="px-3 py-3 text-xs app-copy">
                  {row.current_page_scraped ?? 0}/{row.total_pages ?? 0} pages, {row.current_product_scraped ?? 0}/{row.total_products ?? 0} products
                </td>
                <td className="px-3 py-3 text-xs app-copy-weak">{row.update_date || "-"}</td>
                <td className="px-3 py-3">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => onEdit(row)}
                      className="focus-ring-cyan rounded-lg border border-[var(--status-info-border)] bg-[var(--status-info-bg)] px-3 py-1.5 text-xs font-semibold text-[var(--status-info-text)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isSaving ? "Saving..." : "Edit"}
                    </button>
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => onDelete(row)}
                      title="Delete metadata row"
                      aria-label="Delete metadata row"
                      className="rounded-lg border border-[var(--status-danger-border)] bg-[var(--status-danger-bg)] p-1.5 text-[var(--status-danger-text)] transition hover:-translate-y-0.5 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isDeleting ? (
                        <span className="text-[10px] font-semibold">...</span>
                      ) : (
                        <Trash2 className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
