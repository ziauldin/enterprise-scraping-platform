"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Download, Plus, Upload } from "lucide-react";
import { MultiSelect } from "react-multi-select-component";

import Modal from "@/components/Modal";
import MetadataCreateForm from "@/components/metadata/MetadataCreateForm";
import MetadataEditForm from "@/components/metadata/MetadataEditForm";
import MetadataTable from "@/components/metadata/MetadataTable";
import {
  CreateMetadataFields,
  EditableMetadataFields,
  MetadataListResponse,
  MetadataRecord,
  MetadataRecordResponse,
  MetadataValidationErrors,
} from "@/components/metadata/types";
import {
  hasValidationErrors,
  normalizeCreateMetadataPayload,
  normalizeMetadataPayload,
  validateCreateMetadataDraft,
  validateMetadataDraft,
} from "@/lib/metadataValidation";

const DEFAULT_LIMIT = 25;

interface FiltersResponse {
  success: boolean;
  filters?: {
    regions?: string[];
    countries?: string[];
    brands?: string[];
  };
}

interface ImportMetadataResult {
  success: boolean;
  error?: string;
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
}

interface MultiSelectOption {
  label: string;
  value: string;
}

function toEditable(record: MetadataRecord): EditableMetadataFields {
  return {
    project_id_parsehub: record.project_id_parsehub,
    project_name: record.project_name,
    website_type: record.website_type,
    region: record.region,
    country: record.country,
    brand: record.brand,
    website_url: record.website_url,
    next_page_url: record.next_page_url,
    total_pages: record.total_pages,
    total_products: record.total_products,
    current_page_scraped: record.current_page_scraped,
    current_product_scraped: record.current_product_scraped,
    update_date: record.update_date,
  };
}

function toLocalDateTimeValue(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function buildCreateDraft(): CreateMetadataFields {
  const now = toLocalDateTimeValue(new Date());
  return {
    personal_project_id: "",
    project_id_parsehub: null,
    project_name: null,
    website_type: null,
    last_run_data: null,
    create_date: now,
    update_date: now,
    region: null,
    country: null,
    brand: null,
    website_url: null,
    next_page_url: null,
    total_pages: null,
    total_products: null,
    current_page_scraped: 0,
    current_product_scraped: 0,
  };
}

export default function MetadataPage() {
  const importFileInputRef = useRef<HTMLInputElement | null>(null);
  const [rows, setRows] = useState<MetadataRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedRegions, setSelectedRegions] = useState<string[]>([]);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [selectedBrands, setSelectedBrands] = useState<string[]>([]);
  const [appliedRegions, setAppliedRegions] = useState<string[]>([]);
  const [appliedCountries, setAppliedCountries] = useState<string[]>([]);
  const [appliedBrands, setAppliedBrands] = useState<string[]>([]);
  const [filterOptions, setFilterOptions] = useState<{ regions: string[]; countries: string[]; brands: string[] }>({
    regions: [],
    countries: [],
    brands: [],
  });

  const [editingRecord, setEditingRecord] = useState<MetadataRecord | null>(null);
  const [draft, setDraft] = useState<EditableMetadataFields | null>(null);
  const [validationErrors, setValidationErrors] = useState<MetadataValidationErrors>({});
  const [modalError, setModalError] = useState<string | null>(null);
  const [modalSuccess, setModalSuccess] = useState<string | null>(null);
  const [savingRowId, setSavingRowId] = useState<string | null>(null);
  const [deletingRowId, setDeletingRowId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<MetadataRecord | null>(null);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateMetadataFields>(buildCreateDraft());
  const [createErrors, setCreateErrors] = useState<MetadataValidationErrors>({});
  const [creating, setCreating] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportMetadataResult | null>(null);
  const [exportingMetadata, setExportingMetadata] = useState(false);
  const [pageSuccess, setPageSuccess] = useState<string | null>(null);
  const [highlightedRowId, setHighlightedRowId] = useState<string | null>(null);

  const totalPages = Math.max(1, Math.ceil(total / limit));
  const offset = (page - 1) * limit;

  const toSelectOptions = (values: string[]): MultiSelectOption[] => values.map((value) => ({ label: value, value }));
  const selectedOptions = (values: string[]): MultiSelectOption[] => values.map((value) => ({ label: value, value }));
  const areSameSelections = (left: string[], right: string[]): boolean => {
    if (left.length !== right.length) return false;
    return left.every((value, index) => value === right[index]);
  };
  const hasPendingFilterChanges =
    !areSameSelections(selectedRegions, appliedRegions) ||
    !areSameSelections(selectedCountries, appliedCountries) ||
    !areSameSelections(selectedBrands, appliedBrands);

  const changedFields = useMemo(() => {
    if (!editingRecord || !draft) {
      return new Set<keyof EditableMetadataFields>();
    }

    const original = normalizeMetadataPayload(toEditable(editingRecord));
    const current = normalizeMetadataPayload(draft);
    const changed = new Set<keyof EditableMetadataFields>();

    (Object.keys(current) as Array<keyof EditableMetadataFields>).forEach((key) => {
      if ((original[key] ?? null) !== (current[key] ?? null)) {
        changed.add(key);
      }
    });

    return changed;
  }, [editingRecord, draft]);

  const fetchRows = async (overrideFilters?: {
    regions?: string[];
    countries?: string[];
    brands?: string[];
  }) => {
    setLoading(true);
    setTableError(null);
    try {
      const params = new URLSearchParams({
        limit: String(limit),
        offset: String(offset),
      });
      const requestRegions = overrideFilters?.regions ?? appliedRegions;
      const requestCountries = overrideFilters?.countries ?? appliedCountries;
      const requestBrands = overrideFilters?.brands ?? appliedBrands;
      requestRegions.forEach((region) => params.append("region", region));
      requestCountries.forEach((country) => params.append("country", country));
      requestBrands.forEach((brand) => params.append("brand", brand));
      if (searchTerm.trim()) params.set("search", searchTerm.trim());

      const response = await fetch(`/api/metadata?${params.toString()}`, { cache: "no-store" });
      const payload = (await response.json()) as MetadataListResponse;
      if (!response.ok) {
        throw new Error(payload.error || "Failed to load metadata records");
      }

      setRows(payload.records || []);
      setTotal(payload.total ?? payload.count ?? 0);
    } catch (error) {
      setTableError(error instanceof Error ? error.message : "Failed to load metadata records");
    } finally {
      setLoading(false);
    }
  };

  const fetchFilterOptions = async () => {
    try {
      const response = await fetch("/api/filters", { cache: "no-store" });
      if (!response.ok) {
        return;
      }
      const payload = (await response.json()) as FiltersResponse;
      if (!payload.success) {
        return;
      }
      setFilterOptions({
        regions: payload.filters?.regions || [],
        countries: payload.filters?.countries || [],
        brands: payload.filters?.brands || [],
      });
    } catch {
      // Keep editor usable even if filter options endpoint fails.
    }
  };

  useEffect(() => {
    void fetchFilterOptions();
  }, []);

  useEffect(() => {
    void fetchRows();
  }, [limit, offset, searchTerm, appliedRegions, appliedCountries, appliedBrands]);

  const onSearchSubmit = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setSearchTerm(searchInput.trim());
  };

  const applyFilters = async () => {
    const nextRegions = [...selectedRegions];
    const nextCountries = [...selectedCountries];
    const nextBrands = [...selectedBrands];
    setPage(1);
    setAppliedRegions(nextRegions);
    setAppliedCountries(nextCountries);
    setAppliedBrands(nextBrands);
    await fetchRows({ regions: nextRegions, countries: nextCountries, brands: nextBrands });
  };

  const resetFilters = async () => {
    setPage(1);
    setSelectedRegions([]);
    setSelectedCountries([]);
    setSelectedBrands([]);
    setAppliedRegions([]);
    setAppliedCountries([]);
    setAppliedBrands([]);
    await fetchRows({ regions: [], countries: [], brands: [] });
  };

  const openEditor = (row: MetadataRecord) => {
    setPageSuccess(null);
    setModalError(null);
    setModalSuccess(null);
    setValidationErrors({});
    setEditingRecord(row);
    setDraft(toEditable(row));
  };

  const closeEditor = () => {
    if (savingRowId || deletingRowId) {
      return;
    }
    setEditingRecord(null);
    setDraft(null);
    setValidationErrors({});
    setModalError(null);
    setModalSuccess(null);
  };

  const openCreateModal = () => {
    setPageSuccess(null);
    setCreateErrors({});
    setModalError(null);
    setModalSuccess(null);
    setCreateDraft(buildCreateDraft());
    setIsCreateModalOpen(true);
  };

  const closeCreateModal = () => {
    if (creating) {
      return;
    }
    setIsCreateModalOpen(false);
    setCreateErrors({});
    setModalError(null);
    setModalSuccess(null);
    setCreateDraft(buildCreateDraft());
  };

  const openImportModal = () => {
    setPageSuccess(null);
    setImportError(null);
    setImportResult(null);
    setImportFile(null);
    setIsImportModalOpen(true);
  };

  const closeImportModal = () => {
    if (importing) {
      return;
    }
    setIsImportModalOpen(false);
    setImportError(null);
    setImportResult(null);
    setImportFile(null);
    if (importFileInputRef.current) {
      importFileInputRef.current.value = "";
    }
  };

  const onImportFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] || null;
    setImportError(null);
    setImportResult(null);
    if (!file) {
      setImportFile(null);
      return;
    }

    const lowerName = file.name.toLowerCase();
    const isSupported = lowerName.endsWith(".xlsx") || lowerName.endsWith(".xls") || lowerName.endsWith(".csv");
    if (!isSupported) {
      setImportFile(null);
      setImportError("Unsupported file type. Please upload .xlsx, .xls, or .csv.");
      return;
    }

    setImportFile(file);
  };

  const onImportMetadata = async () => {
    if (!importFile) {
      setImportError("Please choose a file before importing.");
      return;
    }

    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      const formData = new FormData();
      formData.append("file", importFile);
      formData.append("uploaded_by", "metadata_page");

      const response = await fetch("/api/metadata/import", {
        method: "POST",
        body: formData,
      });
      const payload = (await response.json()) as ImportMetadataResult;

      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to import metadata.");
      }

      setImportResult(payload);
      const imported = payload.stats?.imported ?? 0;
      const skipped = payload.stats?.skipped ?? 0;
      setPageSuccess(`Import complete: ${imported} inserted/updated, ${skipped} skipped.`);
      await fetchRows();
      await fetchFilterOptions();
    } catch (error) {
      setImportError(error instanceof Error ? error.message : "Failed to import metadata.");
    } finally {
      setImporting(false);
    }
  };

  const onDownloadTemplate = async () => {
    setPageSuccess(null);
    setTableError(null);
    try {
      const response = await fetch("/api/metadata/template", { cache: "no-store" });
      if (!response.ok) {
        let errorMessage = "Failed to download template.";
        try {
          const data = await response.json();
          errorMessage = data.error || errorMessage;
        } catch {
          // ignore non-json errors
        }
        throw new Error(errorMessage);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "metadata_template.csv";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
      setPageSuccess("Template downloaded successfully.");
    } catch (error) {
      setTableError(error instanceof Error ? error.message : "Failed to download template.");
    }
  };

  const onExportMetadataCsv = async () => {
    if (exportingMetadata) {
      return;
    }

    setExportingMetadata(true);
    setPageSuccess(null);
    setTableError(null);
    try {
      const response = await fetch("/api/metadata/export", { cache: "no-store" });
      if (!response.ok) {
        let errorMessage = "Failed to export metadata CSV.";
        try {
          const data = await response.json();
          errorMessage = data.error || errorMessage;
        } catch {
          // ignore non-json errors
        }
        throw new Error(errorMessage);
      }

      const blob = await response.blob();
      const contentDisposition = response.headers.get("content-disposition") || "";
      const filenameMatch = /filename=\"?([^\";]+)\"?/i.exec(contentDisposition);
      const filename = filenameMatch?.[1] || "metadata_export.csv";

      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
      setPageSuccess(`Metadata export downloaded: ${filename}`);
    } catch (error) {
      setTableError(error instanceof Error ? error.message : "Failed to export metadata CSV.");
    } finally {
      setExportingMetadata(false);
    }
  };

  const onDraftChange = (field: keyof EditableMetadataFields, value: string) => {
    if (!draft) return;
    setDraft((prev) => {
      if (!prev) return prev;
      const asNumberField = ["total_pages", "total_products", "current_page_scraped", "current_product_scraped"].includes(field);
      return {
        ...prev,
        [field]: asNumberField ? (value === "" ? null : Number(value)) : value,
      };
    });
  };

  const onCreateDraftChange = (field: keyof CreateMetadataFields, value: string) => {
    setCreateDraft((prev) => {
      const asNumberField = ["total_pages", "total_products", "current_page_scraped", "current_product_scraped"].includes(field);
      return {
        ...prev,
        [field]: asNumberField ? (value === "" ? null : Number(value)) : value,
      };
    });
  };

  const onRevert = () => {
    if (!editingRecord || !draft || savingRowId) return;
    setDraft(toEditable(editingRecord));
    setValidationErrors({});
    setModalError(null);
  };

  const onSave = async () => {
    if (!editingRecord || !draft || savingRowId) return;

    const normalized = normalizeMetadataPayload(draft);
    const errors = validateMetadataDraft(normalized);
    setValidationErrors(errors);
    if (hasValidationErrors(errors)) {
      setModalError("Fix validation errors before saving.");
      return;
    }
    if (changedFields.size === 0) {
      return;
    }

    const rowId = editingRecord.personal_project_id;
    const previousRows = rows;
    const optimisticRow: MetadataRecord = {
      ...editingRecord,
      ...normalized,
      personal_project_id: rowId,
      id: rowId,
    };

    setSavingRowId(rowId);
    setModalError(null);
    setModalSuccess(null);
    setRows((prev) => prev.map((row) => (row.personal_project_id === rowId ? optimisticRow : row)));

    try {
      const response = await fetch(`/api/metadata/${encodeURIComponent(rowId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(normalized),
      });
      const payload = (await response.json()) as MetadataRecordResponse & { error?: string };
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to save metadata changes");
      }

      const persisted = payload.record || optimisticRow;
      setRows((prev) => prev.map((row) => (row.personal_project_id === rowId ? persisted : row)));
      setEditingRecord(persisted);
      setDraft(toEditable(persisted));
      setModalSuccess("Metadata saved successfully.");
    } catch (error) {
      setRows(previousRows);
      setModalError(error instanceof Error ? error.message : "Failed to save metadata changes");
    } finally {
      setSavingRowId(null);
    }
  };

  const onCreateSave = async () => {
    const normalized = normalizeCreateMetadataPayload(createDraft);
    const errors = validateCreateMetadataDraft(normalized);
    setCreateErrors(errors);
    if (hasValidationErrors(errors)) {
      setModalError("Fix validation errors before creating the record.");
      return;
    }

    setCreating(true);
    setModalError(null);
    setModalSuccess(null);

    try {
      const response = await fetch("/api/metadata", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(normalized),
      });
      const payload = (await response.json()) as MetadataRecordResponse & { error?: string };
      if (!response.ok || !payload.success || !payload.record) {
        throw new Error(payload.error || "Failed to create metadata record");
      }

      const createdRecord = payload.record;
      setRows((prev) => [createdRecord, ...prev.filter((row) => row.personal_project_id !== createdRecord.personal_project_id)].slice(0, limit));
      setTotal((prev) => prev + 1);
      setSearchInput("");
      setSearchTerm("");
      setSelectedRegions([]);
      setSelectedCountries([]);
      setSelectedBrands([]);
      setAppliedRegions([]);
      setAppliedCountries([]);
      setAppliedBrands([]);
      setPage(1);
      setHighlightedRowId(createdRecord.personal_project_id);
      setPageSuccess(`Created metadata record ${createdRecord.personal_project_id}.`);
      setIsCreateModalOpen(false);
      setCreateErrors({});
      setModalError(null);
      setModalSuccess(null);
      setCreateDraft(buildCreateDraft());
    } catch (error) {
      setModalError(error instanceof Error ? error.message : "Failed to create metadata record");
    } finally {
      setCreating(false);
    }
  };

  const openDeleteModal = (row: MetadataRecord) => {
    setPageSuccess(null);
    setTableError(null);
    setDeleteTarget(row);
  };

  const closeDeleteModal = () => {
    if (deletingRowId) return;
    setDeleteTarget(null);
  };

  const onDeleteConfirm = async () => {
    if (!deleteTarget) return;
    const rowId = deleteTarget.personal_project_id;
    setDeletingRowId(rowId);
    setTableError(null);
    setPageSuccess(null);
    try {
      const response = await fetch(`/api/metadata/${encodeURIComponent(rowId)}`, { method: "DELETE" });
      const payload = (await response.json()) as { success?: boolean; error?: string };
      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "Failed to delete metadata record");
      }

      if (editingRecord?.personal_project_id === rowId) {
        setEditingRecord(null);
        setDraft(null);
        setValidationErrors({});
        setModalError(null);
        setModalSuccess(null);
      }

      setRows((prev) => prev.filter((row) => row.personal_project_id !== rowId));
      setTotal((prev) => Math.max(0, prev - 1));
      setPageSuccess(`Deleted metadata record ${rowId}.`);
      setDeleteTarget(null);
      await fetchRows();
      await fetchFilterOptions();
    } catch (deleteError) {
      setTableError(deleteError instanceof Error ? deleteError.message : "Failed to delete metadata record");
    } finally {
      setDeletingRowId(null);
    }
  };

  return (
    <main className="app-page flex-1 overflow-y-auto">

      {/* ── Top bar ─────────────────────────────────────────── */}
      <div className="app-page-header px-8 py-6">
        <p className="section-label">Data Management</p>
        <div className="mt-1 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <h1 className="app-title text-[28px] font-semibold tracking-[-0.02em]">Metadata</h1>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={openCreateModal} className="btn-primary h-9 px-4 text-sm shrink-0">
              <Plus className="h-3.5 w-3.5" />
              Add New Project
            </button>
            <button type="button" onClick={openImportModal} className="btn-secondary h-9 px-4 text-sm shrink-0">
              <Upload className="h-3.5 w-3.5" />
              Import Metadata
            </button>
            <button
              type="button"
              onClick={() => void onExportMetadataCsv()}
              disabled={exportingMetadata}
              className="btn-secondary h-9 px-4 text-sm shrink-0 disabled:opacity-40"
            >
              <Download className="h-3.5 w-3.5" />
              {exportingMetadata ? "Exporting…" : "Export Metadata CSV"}
            </button>
            <button type="button" onClick={() => void onDownloadTemplate()} className="btn-ghost h-9 px-4 text-sm shrink-0">
              <Download className="h-3.5 w-3.5" />
              Download Template
            </button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-[1280px] px-8 py-6 space-y-5">

        {/* ── Filters / search ────────────────────────────────── */}
        <div className="saas-card space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <form onSubmit={onSearchSubmit} className="flex flex-1 gap-2">
              <input
                type="text"
                placeholder="Search project name or ParseHub token…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                className="saas-input flex-1 text-sm"
              />
              <button type="submit" className="btn-primary h-9 px-4 text-sm">Search</button>
            </form>
            <button
              type="button"
              onClick={() => {
                setSearchInput("");
                setSearchTerm("");
                setSelectedRegions([]);
                setSelectedCountries([]);
                setSelectedBrands([]);
                setAppliedRegions([]);
                setAppliedCountries([]);
                setAppliedBrands([]);
                setPage(1);
              }}
              className="btn-ghost h-9 px-4 text-sm"
            >
              Reset
            </button>
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            <MultiSelect
              className="metadata-multiselect"
              options={toSelectOptions(filterOptions.regions)}
              value={selectedOptions(selectedRegions)}
              onChange={(options: MultiSelectOption[]) => setSelectedRegions(options.map((option: MultiSelectOption) => option.value))}
              labelledBy="Select Regions"
              hasSelectAll={false}
              overrideStrings={{ selectSomeItems: "All Regions" }}
            />
            <MultiSelect
              className="metadata-multiselect"
              options={toSelectOptions(filterOptions.countries)}
              value={selectedOptions(selectedCountries)}
              onChange={(options: MultiSelectOption[]) => setSelectedCountries(options.map((option: MultiSelectOption) => option.value))}
              labelledBy="Select Countries"
              hasSelectAll={false}
              overrideStrings={{ selectSomeItems: "All Countries" }}
            />
            <MultiSelect
              className="metadata-multiselect"
              options={toSelectOptions(filterOptions.brands)}
              value={selectedOptions(selectedBrands)}
              onChange={(options: MultiSelectOption[]) => setSelectedBrands(options.map((option: MultiSelectOption) => option.value))}
              labelledBy="Select Brands"
              hasSelectAll={false}
              overrideStrings={{ selectSomeItems: "All Brands" }}
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => void resetFilters()} className="btn-ghost h-9 px-4 text-sm">
              Reset Filters
            </button>
            <button
              type="button"
              onClick={() => void applyFilters()}
              disabled={!hasPendingFilterChanges}
              className="btn-primary h-9 px-4 text-sm disabled:opacity-40"
            >
              Apply Filters
            </button>
          </div>
        </div>

        {tableError && (
          <div className="app-alert app-alert-error rounded-lg px-4 py-3 text-sm">{tableError}</div>
        )}

        {pageSuccess && (
          <div className="app-alert app-alert-success rounded-lg px-4 py-3 text-sm">{pageSuccess}</div>
        )}

        {loading ? (
          <div className="app-copy flex items-center justify-center gap-2 py-12 text-sm">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--border-default)] border-t-[var(--accent-primary)]" />
            Loading records…
          </div>
        ) : (
          <MetadataTable
            rows={rows}
            savingRowId={savingRowId}
            deletingRowId={deletingRowId}
            onEdit={openEditor}
            onDelete={openDeleteModal}
            highlightedRowId={highlightedRowId}
          />
        )}

        {/* Pagination */}
        <div className="app-copy flex flex-wrap items-center justify-between gap-3 text-sm">
          <p>Showing {rows.length} of {total} records</p>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-xs">
              Rows
              <select
                value={limit}
                onChange={(e) => { setLimit(Number(e.target.value)); setPage(1); }}
                className="saas-select w-16 text-xs"
              >
                <option value={10}>10</option>
                <option value={25}>25</option>
                <option value={50}>50</option>
              </select>
            </label>
            <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className="btn-ghost h-8 px-3 text-xs disabled:opacity-40">Previous</button>
            <span className="text-xs">Page {page} / {totalPages}</span>
            <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages} className="btn-ghost h-8 px-3 text-xs disabled:opacity-40">Next</button>
          </div>
        </div>
      </div>

      <style jsx global>{`
        .metadata-multiselect {
          --rmsc-bg: var(--bg-surface);
          --rmsc-border: var(--border-default);
          --rmsc-main: var(--accent-primary);
          --rmsc-hover: var(--bg-subtle);
          --rmsc-selected: color-mix(in srgb, var(--accent-primary) 18%, var(--bg-surface));
          --rmsc-gray: var(--text-secondary);
        }
        .metadata-multiselect .dropdown-content .panel-content {
          background: var(--bg-elevated, var(--bg-surface));
          border: 1px solid var(--border-default);
          color: var(--text-primary);
        }
        .metadata-multiselect .search input,
        .metadata-multiselect .item-renderer span,
        .metadata-multiselect .dropdown-heading-value {
          color: var(--text-primary);
        }
      `}</style>
      <Modal
        isOpen={isCreateModalOpen}
        onClose={closeCreateModal}
        title="Add New Metadata Project"
        size="large"
      >
        <div className="space-y-4">
          <div className="app-surface-elevated rounded-lg px-3 py-2 text-sm app-copy">
            Create a new row in the metadata table. Personal Project ID and Project Name are required.
          </div>

          {modalSuccess && (
            <div className="app-alert app-alert-success rounded-lg px-3 py-2 text-sm">{modalSuccess}</div>
          )}
          {modalError && (
            <div className="app-alert app-alert-error rounded-lg px-3 py-2 text-sm">{modalError}</div>
          )}

          <MetadataCreateForm
            draft={createDraft}
            errors={createErrors}
            onChange={onCreateDraftChange}
            filterOptions={filterOptions}
          />

          <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border-default)] pt-4">
            <button type="button" onClick={closeCreateModal} disabled={creating} className="btn-ghost h-9 px-4 text-sm disabled:opacity-40">
              Cancel
            </button>
            <button type="button" onClick={() => void onCreateSave()} disabled={creating} className="btn-primary h-9 px-4 text-sm disabled:opacity-40">
              {creating ? "Creating…" : "Create Project"}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={isImportModalOpen}
        onClose={closeImportModal}
        title="Import Metadata"
        size="medium"
      >
        <div className="space-y-4">
          <div className="app-surface-elevated rounded-lg px-3 py-2 text-sm app-copy">
            Upload a CSV or Excel file to bulk insert/update metadata rows. The file must follow the downloadable template schema.
          </div>

          {importError && (
            <div className="app-alert app-alert-error rounded-lg px-3 py-2 text-sm">{importError}</div>
          )}

          {importResult?.stats && (
            <div className="app-alert app-alert-success rounded-lg px-3 py-2 text-sm">
              Imported: {importResult.stats.imported} | Skipped: {importResult.stats.skipped} | Total rows: {importResult.stats.total_records}
            </div>
          )}

          <div className="space-y-2">
            <label className="app-field-label block text-[11px] font-semibold uppercase tracking-[0.14em]">File</label>
            <input
              ref={importFileInputRef}
              type="file"
              accept=".xlsx,.xls,.csv"
              onChange={onImportFileChange}
              disabled={importing}
              className="saas-input w-full text-sm"
            />
            <p className="app-copy-weak text-xs">Supported formats: .xlsx, .xls, .csv</p>
            {importFile && (
              <p className="app-copy text-xs">
                Selected: <span className="app-title font-medium">{importFile.name}</span> ({Math.max(1, Math.round(importFile.size / 1024))} KB)
              </p>
            )}
          </div>

          <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border-default)] pt-4">
            <button type="button" onClick={() => void onDownloadTemplate()} className="btn-ghost h-9 px-4 text-sm">
              Download Template
            </button>
            <button type="button" onClick={closeImportModal} disabled={importing} className="btn-ghost h-9 px-4 text-sm disabled:opacity-40">
              Cancel
            </button>
            <button type="button" onClick={() => void onImportMetadata()} disabled={!importFile || importing} className="btn-primary h-9 px-4 text-sm disabled:opacity-40">
              {importing ? "Importing…" : "Import Metadata"}
            </button>
          </div>
        </div>
      </Modal>

      <Modal
        isOpen={!!editingRecord && !!draft}
        onClose={closeEditor}
        title="Edit Metadata Record"
        size="large"
      >
        {editingRecord && draft && (
          <div className="space-y-4">
            <div className="app-surface-elevated rounded-lg px-3 py-2 text-sm app-copy">
              <span className="app-title font-semibold">Personal Project ID:</span>{" "}
              <span className="app-link font-mono">{editingRecord.personal_project_id}</span>
            </div>

            {modalSuccess && (
              <div className="app-alert app-alert-success rounded-lg px-3 py-2 text-sm">{modalSuccess}</div>
            )}
            {modalError && (
              <div className="app-alert app-alert-error rounded-lg px-3 py-2 text-sm">{modalError}</div>
            )}

            <MetadataEditForm
              draft={draft}
              errors={validationErrors}
              changedFields={changedFields}
              onChange={onDraftChange}
            />

            <div className="flex flex-wrap justify-end gap-2 border-t border-[var(--border-default)] pt-4">
              <button
                type="button"
                onClick={onRevert}
                disabled={changedFields.size === 0 || !!savingRowId}
                className="btn-secondary h-9 px-4 text-sm disabled:opacity-40"
              >
                Revert
              </button>
              <button
                type="button"
                onClick={closeEditor}
                disabled={!!savingRowId}
                className="btn-ghost h-9 px-4 text-sm disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void onSave()}
                disabled={changedFields.size === 0 || !!savingRowId}
                className="btn-primary h-9 px-4 text-sm disabled:opacity-40"
              >
                {savingRowId ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        isOpen={!!deleteTarget}
        onClose={closeDeleteModal}
        title="Delete Metadata Record"
        size="small"
      >
        {deleteTarget && (
          <div className="space-y-4">
            <div className="app-alert app-alert-error rounded-lg px-3 py-2 text-sm">
              This action cannot be undone.
            </div>
            <div className="app-copy text-sm">
              Are you sure you want to delete metadata record{" "}
              <span className="app-title font-mono">{deleteTarget.personal_project_id}</span>?
            </div>
            <div className="flex justify-end gap-2 border-t border-[var(--border-default)] pt-4">
              <button
                type="button"
                onClick={closeDeleteModal}
                disabled={!!deletingRowId}
                className="btn-ghost h-9 px-4 text-sm disabled:opacity-40"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void onDeleteConfirm()}
                disabled={!!deletingRowId}
                className="btn-secondary h-9 px-4 text-sm disabled:opacity-40"
              >
                {deletingRowId ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </main>
  );
}
