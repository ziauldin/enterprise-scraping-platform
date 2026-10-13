"use client";

import { EditableMetadataFields, MetadataValidationErrors } from "@/components/metadata/types";

interface MetadataEditFormProps {
  draft: EditableMetadataFields;
  errors: MetadataValidationErrors;
  changedFields: Set<keyof EditableMetadataFields>;
  onChange: (field: keyof EditableMetadataFields, value: string) => void;
}

const NUMBER_FIELDS: Array<keyof EditableMetadataFields> = [
  "total_pages",
  "total_products",
  "current_page_scraped",
  "current_product_scraped",
];

function inputClass(changed: boolean, hasError: boolean): string {
  if (hasError) {
    return "app-input focus-ring-cyan w-full border-red-500/60 focus:border-red-400";
  }
  if (changed) {
    return "app-input focus-ring-cyan w-full border-amber-500/60 focus:border-amber-400";
  }
  return "app-input focus-ring-cyan w-full";
}

function Field({
  label,
  field,
  value,
  onChange,
  changed,
  error,
  type = "text",
}: {
  label: string;
  field: keyof EditableMetadataFields;
  value: string;
  onChange: (field: keyof EditableMetadataFields, value: string) => void;
  changed: boolean;
  error?: string;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="app-field-label mb-1 block text-[11px] font-semibold uppercase tracking-[0.14em]">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
        className={inputClass(changed, !!error)}
      />
      {error && <span className="mt-1 block text-xs text-red-300">{error}</span>}
    </label>
  );
}

export default function MetadataEditForm({ draft, errors, changedFields, onChange }: MetadataEditFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Field
          label="Project ID (ParseHub)"
          field="project_id_parsehub"
          value={draft.project_id_parsehub ?? ""}
          onChange={onChange}
          changed={changedFields.has("project_id_parsehub")}
        />
        <Field
          label="Project Name"
          field="project_name"
          value={draft.project_name ?? ""}
          onChange={onChange}
          changed={changedFields.has("project_name")}
          error={errors.project_name}
        />
        <label className="block">
          <span className="app-field-label mb-1 block text-[11px] font-semibold uppercase tracking-[0.14em]">Website Type</span>
          <select
            value={draft.website_type ?? ""}
            onChange={(e) => onChange("website_type" as keyof EditableMetadataFields, e.target.value)}
            className={inputClass(changedFields.has("website_type"), !!errors.website_type)}
          >
            <option value="">— Select —</option>
            <option value="Collective">Collective</option>
            <option value="Individual">Individual</option>
          </select>
          {errors.website_type && <span className="mt-1 block text-xs text-red-300">{errors.website_type}</span>}
        </label>
        <Field
          label="Region"
          field="region"
          value={draft.region ?? ""}
          onChange={onChange}
          changed={changedFields.has("region")}
        />
        <Field
          label="Country"
          field="country"
          value={draft.country ?? ""}
          onChange={onChange}
          changed={changedFields.has("country")}
        />
        <Field
          label="Brand"
          field="brand"
          value={draft.brand ?? ""}
          onChange={onChange}
          changed={changedFields.has("brand")}
        />
        <Field
          label="Update Date"
          field="update_date"
          value={draft.update_date ?? ""}
          onChange={onChange}
          changed={changedFields.has("update_date")}
        />
      </div>

      <Field
        label="Website URL"
        field="website_url"
        value={draft.website_url ?? ""}
        onChange={onChange}
        changed={changedFields.has("website_url")}
        error={errors.website_url}
      />

      <Field
        label="Next Page URL"
        field="next_page_url"
        value={draft.next_page_url ?? ""}
        onChange={onChange}
        changed={changedFields.has("next_page_url")}
        error={errors.next_page_url}
      />

      <div className="grid gap-4 md:grid-cols-2">
        {NUMBER_FIELDS.map((field) => (
          <Field
            key={field}
            label={field
              .split("_")
              .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
              .join(" ")}
            field={field}
            value={draft[field] === null || draft[field] === undefined ? "" : String(draft[field])}
            onChange={onChange}
            changed={changedFields.has(field)}
            error={errors[field as keyof MetadataValidationErrors]}
            type="number"
          />
        ))}
      </div>
    </div>
  );
}
