import { CreateMetadataFields, EditableMetadataFields, MetadataValidationErrors } from "@/components/metadata/types";

const ALLOWED_WEBSITE_TYPES = new Set(["Collective", "Individual"]);

const INTEGER_FIELDS: Array<keyof EditableMetadataFields> = [
  "total_pages",
  "total_products",
  "current_page_scraped",
  "current_product_scraped",
];

function isValidUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function normalizeMetadataPayload(draft: EditableMetadataFields): EditableMetadataFields {
  const normalized: EditableMetadataFields = { ...draft };
  const writable = normalized as unknown as Record<string, unknown>;

  normalized.project_name = (normalized.project_name ?? "").trim();
  normalized.project_id_parsehub = (normalized.project_id_parsehub ?? "").trim() || null;
  normalized.region = (normalized.region ?? "").trim() || null;
  normalized.country = (normalized.country ?? "").trim() || null;
  normalized.brand = (normalized.brand ?? "").trim() || null;
  normalized.website_url = (normalized.website_url ?? "").trim() || null;
  normalized.next_page_url = (normalized.next_page_url ?? "").trim() || null;
  normalized.update_date = (normalized.update_date ?? "").trim() || null;
  const websiteTypeRaw = (normalized.website_type ?? "").trim();
  normalized.website_type = (websiteTypeRaw as "Collective" | "Individual" | null) || null;

  for (const field of INTEGER_FIELDS) {
    const value = normalized[field];
    if (value === null || value === undefined || value === "") {
      writable[field] = null;
      continue;
    }
    const parsed = Number(value);
    writable[field] = Number.isFinite(parsed) ? Math.trunc(parsed) : value;
  }

  return normalized;
}

export function normalizeCreateMetadataPayload(draft: CreateMetadataFields): CreateMetadataFields {
  const normalized: CreateMetadataFields = {
    ...draft,
    ...normalizeMetadataPayload(draft),
  };

  normalized.personal_project_id = (normalized.personal_project_id ?? "").trim();
  normalized.last_run_data = (normalized.last_run_data ?? "").trim() || null;
  normalized.create_date = (normalized.create_date ?? "").trim() || null;

  return normalized;
}

export function validateMetadataDraft(draft: EditableMetadataFields): MetadataValidationErrors {
  const errors: MetadataValidationErrors = {};

  const projectName = (draft.project_name ?? "").trim();
  if (!projectName) {
    errors.project_name = "Project name is required.";
  }

  if (draft.website_url && !isValidUrl(String(draft.website_url))) {
    errors.website_url = "Website URL must be a valid http/https URL.";
  }
  if (draft.next_page_url && !isValidUrl(String(draft.next_page_url))) {
    errors.next_page_url = "Next page URL must be a valid http/https URL.";
  }

  for (const field of INTEGER_FIELDS) {
    const value = draft[field];
    if (value === null || value === undefined || value === "") {
      continue;
    }
    const parsed = Number(value);
    if (!Number.isInteger(parsed) || parsed < 0) {
      errors[field as keyof MetadataValidationErrors] = "Must be a non-negative integer.";
    }
  }

  if (draft.website_type && !ALLOWED_WEBSITE_TYPES.has(draft.website_type)) {
    errors.website_type = "Website Type must be Collective or Individual.";
  }

  return errors;
}

export function validateCreateMetadataDraft(draft: CreateMetadataFields): MetadataValidationErrors {
  const errors = validateMetadataDraft(draft);

  if (!(draft.personal_project_id ?? "").trim()) {
    errors.personal_project_id = "Personal Project ID is required.";
  }

  return errors;
}

export function hasValidationErrors(errors: MetadataValidationErrors): boolean {
  return Object.keys(errors).length > 0;
}
