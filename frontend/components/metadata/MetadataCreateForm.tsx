"use client";

import { CreateMetadataFields, MetadataValidationErrors } from "@/components/metadata/types";

interface MetadataCreateFormProps {
  draft: CreateMetadataFields;
  errors: MetadataValidationErrors;
  onChange: (field: keyof CreateMetadataFields, value: string) => void;
  filterOptions: {
    regions: string[];
    countries: string[];
    brands: string[];
  };
}

const NUMBER_FIELDS: Array<keyof CreateMetadataFields> = [
  "total_pages",
  "total_products",
  "current_page_scraped",
  "current_product_scraped",
];

function inputClass(hasError: boolean): string {
  if (hasError) {
    return "app-input focus-ring-cyan w-full border-red-500/60 focus:border-red-400";
  }
  return "app-input focus-ring-cyan w-full";
}

function TextField({
  label,
  field,
  value,
  onChange,
  error,
  type = "text",
  placeholder,
  listId,
}: {
  label: string;
  field: keyof CreateMetadataFields;
  value: string;
  onChange: (field: keyof CreateMetadataFields, value: string) => void;
  error?: string;
  type?: string;
  placeholder?: string;
  listId?: string;
}) {
  return (
    <label className="block">
      <span className="app-field-label mb-1 block text-[11px] font-semibold uppercase tracking-[0.14em]">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(field, event.target.value)}
        placeholder={placeholder}
        list={listId}
        className={inputClass(!!error)}
      />
      {error && <span className="mt-1 block text-xs text-red-500">{error}</span>}
    </label>
  );
}

export default function MetadataCreateForm({ draft, errors, onChange, filterOptions }: MetadataCreateFormProps) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <TextField
          label="Personal Project ID"
          field="personal_project_id"
          value={draft.personal_project_id}
          onChange={onChange}
          error={errors.personal_project_id}
          placeholder="Unique metadata row id"
        />
        <TextField
          label="Project ID (ParseHub)"
          field="project_id_parsehub"
          value={draft.project_id_parsehub ?? ""}
          onChange={onChange}
          placeholder="Optional ParseHub token"
        />
        <TextField
          label="Project Name"
          field="project_name"
          value={draft.project_name ?? ""}
          onChange={onChange}
          error={errors.project_name}
        />
        <label className="block">
          <span className="app-field-label mb-1 block text-[11px] font-semibold uppercase tracking-[0.14em]">Website Type</span>
          <select
            value={draft.website_type ?? ""}
            onChange={(e) => onChange("website_type" as keyof CreateMetadataFields, e.target.value)}
            className={inputClass(!!errors.website_type)}
          >
            <option value="">— Select —</option>
            <option value="Collective">Collective</option>
            <option value="Individual">Individual</option>
          </select>
          {errors.website_type && <span className="mt-1 block text-xs text-red-500">{errors.website_type}</span>}
        </label>
        <TextField
          label="Last Run Data"
          field="last_run_data"
          value={draft.last_run_data ?? ""}
          onChange={onChange}
          type="datetime-local"
        />
        <TextField
          label="Create Date"
          field="create_date"
          value={draft.create_date ?? ""}
          onChange={onChange}
          type="datetime-local"
        />
        <TextField
          label="Update Date"
          field="update_date"
          value={draft.update_date ?? ""}
          onChange={onChange}
          type="datetime-local"
        />
        <TextField
          label="Region"
          field="region"
          value={draft.region ?? ""}
          onChange={onChange}
          listId="metadata-region-options"
        />
        <TextField
          label="Country"
          field="country"
          value={draft.country ?? ""}
          onChange={onChange}
          listId="metadata-country-options"
        />
        <TextField
          label="Brand"
          field="brand"
          value={draft.brand ?? ""}
          onChange={onChange}
          listId="metadata-brand-options"
        />
      </div>

      <TextField
        label="Website URL"
        field="website_url"
        value={draft.website_url ?? ""}
        onChange={onChange}
        error={errors.website_url}
        placeholder="https://example.com"
      />

      <TextField
        label="Next Page URL"
        field="next_page_url"
        value={draft.next_page_url ?? ""}
        onChange={onChange}
        error={errors.next_page_url}
        placeholder="https://example.com/page/2"
      />

      <div className="grid gap-4 md:grid-cols-2">
        {NUMBER_FIELDS.map((field) => (
          <TextField
            key={field}
            label={field
              .split("_")
              .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
              .join(" ")}
            field={field}
            value={draft[field] === null || draft[field] === undefined ? "" : String(draft[field])}
            onChange={onChange}
            error={errors[field as keyof MetadataValidationErrors]}
            type="number"
          />
        ))}
      </div>

      <datalist id="metadata-region-options">
        {filterOptions.regions.map((region) => <option key={region} value={region} />)}
      </datalist>
      <datalist id="metadata-country-options">
        {filterOptions.countries.map((country) => <option key={country} value={country} />)}
      </datalist>
      <datalist id="metadata-brand-options">
        {filterOptions.brands.map((brand) => <option key={brand} value={brand} />)}
      </datalist>
    </div>
  );
}