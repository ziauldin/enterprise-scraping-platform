export interface MetadataRecord {
  personal_project_id: string;
  id?: string;
  project_id_parsehub: string | null;
  project_name: string | null;
  website_type: "Collective" | "Individual" | null;
  last_run_data: string | null;
  create_date: string | null;
  region: string | null;
  country: string | null;
  brand: string | null;
  website_url: string | null;
  next_page_url: string | null;
  total_pages: number | null;
  total_products: number | null;
  current_page_scraped: number | null;
  current_product_scraped: number | null;
  update_date: string | null;
}

export interface MetadataListResponse {
  success: boolean;
  records: MetadataRecord[];
  count: number;
  total?: number;
  limit?: number;
  offset?: number;
  error?: string;
}

export interface MetadataRecordResponse {
  success: boolean;
  record?: MetadataRecord;
  error?: string;
}

export interface MetadataFilters {
  region: string;
  country: string;
  brand: string;
}

export interface MetadataValidationErrors {
  personal_project_id?: string;
  project_name?: string;
  website_url?: string;
  next_page_url?: string;
  total_pages?: string;
  total_products?: string;
  current_page_scraped?: string;
  current_product_scraped?: string;
  website_type?: string;
}

export interface EditableMetadataFields {
  project_id_parsehub: string | null;
  project_name: string | null;
  website_type: "Collective" | "Individual" | null;
  region: string | null;
  country: string | null;
  brand: string | null;
  website_url: string | null;
  next_page_url: string | null;
  total_pages: number | null;
  total_products: number | null;
  current_page_scraped: number | null;
  current_product_scraped: number | null;
  update_date: string | null;
}

export interface CreateMetadataFields extends EditableMetadataFields {
  personal_project_id: string;
  last_run_data: string | null;
  create_date: string | null;
}
