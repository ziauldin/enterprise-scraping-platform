#!/usr/bin/env python3
"""
ParseHub Data Ingestion Service
Fetches completed run data from ParseHub API and stores it in the database
"""
from __future__ import annotations

import requests
import json
import os
import time
import threading
import traceback
from datetime import datetime, timedelta
from dotenv import load_dotenv
from database import get_database

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, 'backend', '.env'))

API_KEY = os.getenv('PARSEHUB_API_KEY')
BASE_URL = 'https://www.parsehub.com/api/v2'


_INGESTION_SEMAPHORE = threading.BoundedSemaphore(
    value=max(1, min(int(os.getenv('PARSEHUB_MAX_INFLIGHT', '4')), 16))
)
_LAST_INGESTION_REQUEST_AT = 0.0
_INGESTION_RATE_LOCK = threading.Lock()


class ParseHubDataIngestor:
    def __init__(self):
        self.db = get_database()
        self.api_key = API_KEY
        if not self.api_key:
            raise Exception("PARSEHUB_API_KEY not configured")

    def _request_with_retry(self, path: str) -> requests.Response:
        max_attempts = max(1, int(os.getenv('PARSEHUB_RETRY_MAX_ATTEMPTS', '4')))
        backoff_base = float(os.getenv('PARSEHUB_RETRY_BACKOFF_SECONDS', '0.5'))
        timeout_seconds = int(os.getenv('PARSEHUB_TIMEOUT_SECONDS', '30'))
        sustained_interval = 1.0 / max(0.1, float(os.getenv('PARSEHUB_SUSTAINED_RPS', '2')))

        for attempt in range(1, max_attempts + 1):
            global _LAST_INGESTION_REQUEST_AT
            with _INGESTION_RATE_LOCK:
                now = time.monotonic()
                wait_seconds = max(0.0, (_LAST_INGESTION_REQUEST_AT + sustained_interval) - now)
                if wait_seconds > 0:
                    time.sleep(wait_seconds)
                _LAST_INGESTION_REQUEST_AT = time.monotonic()

            acquired = _INGESTION_SEMAPHORE.acquire(timeout=timeout_seconds)
            if not acquired:
                if attempt >= max_attempts:
                    raise RuntimeError('Timed out waiting for ParseHub ingestion slot')
                time.sleep(backoff_base * (2 ** (attempt - 1)))
                continue
            try:
                response = requests.get(
                    f'{BASE_URL}{path}',
                    params={'api_key': self.api_key},
                    timeout=timeout_seconds,
                )
                if response.status_code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                    time.sleep(backoff_base * (2 ** (attempt - 1)))
                    continue
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt >= max_attempts:
                    raise
                time.sleep(backoff_base * (2 ** (attempt - 1)))
            finally:
                _INGESTION_SEMAPHORE.release()

        raise RuntimeError('ParseHub ingestion request exhausted retries')

    def get_run_data(self, run_token: str) -> dict:
        """Fetch detailed run data from ParseHub API"""
        try:
            response = self._request_with_retry(f'/runs/{run_token}')
            return response.json()
        except Exception as e:
            print(f"Error fetching run data for {run_token}: {e}")
            return None

    def get_run_output_data(self, run_token: str) -> list:
        """
        Fetch the actual extracted data from a run
        Uses the /data endpoint which contains the scraped data
        """
        try:
            # The /data endpoint returns the actual extracted data
            response = self._request_with_retry(f'/runs/{run_token}/data')

            if response.status_code == 200:
                data = response.json()

                # The response structure depends on the ParseHub template
                # Extract products from the nested structure
                products = self._extract_products_from_structure(data)
                return products
            else:
                print(f"Data endpoint returned {response.status_code}")
                return []

        except Exception as e:
            print(f"Error fetching output data for {run_token}: {e}")
            return []

    def _extract_products_from_structure(self, data: any, max_depth: int = 5) -> list:
        """
        Recursively extract product records from nested ParseHub data structure
        Handles various nesting levels and key names
        """
        if max_depth <= 0:
            return []

        products = []

        if isinstance(data, list):
            for item in data:
                products.extend(
                    self._extract_products_from_structure(item, max_depth - 1))

        elif isinstance(data, dict):
            # Check for direct product data indicators
            has_product_fields = any(key.lower() in ['part_number', 'product', 'name', 'price', 'url']
                                     for key in data.keys())

            if has_product_fields and 'url' in data or 'product' not in data:
                # This looks like a product record
                # Normalize the product data
                normalized = self._normalize_product_record(data)
                if normalized:
                    products.append(normalized)

            # Recursively search nested structures
            for key, value in data.items():
                if key.lower() in ['product', 'products', 'items', 'results', 'records', 'entries', 'data']:
                    if isinstance(value, (list, dict)):
                        products.extend(
                            self._extract_products_from_structure(value, max_depth - 1))
                elif isinstance(value, (list, dict)) and not isinstance(value, str):
                    # Recursively search nested objects
                    nested_products = self._extract_products_from_structure(
                        value, max_depth - 1)
                    products.extend(nested_products)

        return products

    def _normalize_product_record(self, data: dict) -> dict:
        """
        Normalize a product record to match standard column names
        """
        if not isinstance(data, dict):
            return None

        # If it's empty or doesn't look like product data, skip it
        if not data or (len(data) == 1 and 'product' in data):
            return None

        normalized = {}

        # Column name mappings
        mapping = {
            'part_number': ['part_number', 'partnumber', 'sku', 'article', 'product_code'],
            'name': ['name', 'product_name', 'title', 'product_title', 'description'],
            'brand': ['brand', 'manufacturer', 'vendor'],
            'list_price': ['list_price', 'original_price', 'rrp', 'msrp'],
            'sale_price': ['sale_price', 'price', 'current_price', 'selling_price'],
            'case_unit_price': ['case_unit_price', 'case_price', 'unit_price'],
            'country': ['country', 'location', 'region'],
            'currency': ['currency', 'price_currency'],
            'product_url': ['product_url', 'url', 'link', 'href'],
            'page_number': ['page_number', 'page', 'page_num'],
            'extraction_date': ['extraction_date', 'date', 'scraped_date']
        }

        # Map fields
        for standard_key, possible_keys in mapping.items():
            for key, value in data.items():
                if key.lower() in [pk.lower() for pk in possible_keys]:
                    normalized[standard_key] = value
                    break

        # Copy any unmapped fields as-is (for user-defined columns)
        mapped_keys_lower = set()
        for possible_keys in mapping.values():
            for pk in possible_keys:
                mapped_keys_lower.add(pk.lower())

        for key, value in data.items():
            if key.lower() not in mapped_keys_lower and key not in ['product']:
                # Add custom columns
                normalized[key] = value

        return normalized if normalized else None

    def parse_run_data(self, run_data: dict) -> list:
        """
        Parse run data from ParseHub format to product list
        Handles various data structures that ParseHub might return
        """
        if not run_data:
            return []

        products = []

        # Try to extract data from common ParseHub response structures
        # Structure 1: Direct 'data' key with list of items
        if 'data' in run_data and isinstance(run_data['data'], list):
            products.extend(run_data['data'])

        # Structure 2: Nested data structure with items/results
        elif 'data' in run_data and isinstance(run_data['data'], dict):
            data = run_data['data']

            # Try common nested keys
            for key in ['items', 'results', 'records', 'products', 'entries']:
                if key in data and isinstance(data[key], list):
                    products.extend(data[key])
                    break

            # If no nested key found, try all dict values that are lists
            if not products:
                for value in data.values():
                    if isinstance(value, list):
                        products.extend(value)
                        break

        # If still no products, the entire data might be a list
        elif isinstance(run_data, list):
            products = run_data

        return products

    def ingest_run(
        self,
        project_id: int,
        project_token: str,
        run_token: str,
        project_run_cumulative_id: str | None = None,
    ) -> dict:
        """
        Ingest data from a specific ParseHub run into the database

        Args:
            project_id: Database project ID
            project_token: ParseHub project token
            run_token: ParseHub run token

        Returns:
            Status dictionary with insertion results
        """
        print(f"\n[INGEST] Starting data ingestion for run {run_token}")

        # Get run status
        run_data = self.get_run_data(run_token)

        if not run_data:
            return {'success': False, 'error': 'Could not fetch run data'}

        status = run_data.get('status')
        data_ready = run_data.get('data_ready')

        print(f"[INGEST] Run status: {status}, Data ready: {data_ready}")

        if status != 'complete' and not data_ready:
            return {
                'success': False,
                'message': f'Run not complete yet. Status: {status}',
                'inserted': 0
            }

        # Get the run record from database
        run_id = self._get_or_create_run(project_id, run_token, run_data)

        if not project_run_cumulative_id:
            run_record = self.db.get_run_by_token(run_token)
            project_run_cumulative_id = run_record.get('project_run_cumulative_id') if run_record else None
        if not project_run_cumulative_id:
            project_run_cumulative_id = self.db.attach_run_to_cumulative_session(
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                force_new_session=False,
            )

        # Fetch the actual output data
        print(f"[INGEST] Fetching output data for run...")
        try:
            products = self.get_run_output_data(run_token)
            print(
                f"[INGEST] Got {len(products) if products else 0} products from get_run_output_data")
        except Exception as e:
            print(f"[INGEST] Error in get_run_output_data: {e}")
            products = None

        if not products:
            print(
                f"[INGEST] No output data found ({products}), trying alternative extraction...")
            try:
                products = self.parse_run_data(run_data)
                print(
                    f"[INGEST] Got {len(products) if products else 0} products from parse_run_data")
            except Exception as e:
                print(f"[INGEST] Error in parse_run_data: {e}")
                products = None

        if not products:
            print(f"[INGEST] No product data found in run")
            return {
                'success': True,
                'message': 'Run complete but no product data found',
                'inserted': 0
            }

        # Ensure it's a list
        if isinstance(products, dict):
            # If it's a dict, extract list from common keys
            for key in ['data', 'items', 'results', 'records', 'products', 'entries']:
                if key in products and isinstance(products[key], list):
                    products = products[key]
                    break
            else:
                # If still a dict, wrap in list
                products = [products]

        if not isinstance(products, list):
            products = [products]

        print(f"[INGEST] Found {len(products)} product records in run data")

        # Add run metadata to each product
        for product in products:
            if isinstance(product, dict):
                product['run_token'] = run_token
                # Preserve page number if it exists
                if 'page_number' not in product and 'page' in product:
                    product['page_number'] = product['page']

        # Insert into database
        try:
            result = self.db.insert_product_data(
                project_id=project_id,
                run_id=run_id,
                run_token=run_token,
                project_run_cumulative_id=project_run_cumulative_id,
                product_data_list=products
            )
        except Exception as exc:
            print(f"[INGEST] ❌ insert_product_data failed for run {run_token}: {exc}")
            traceback.print_exc()
            return {
                'success': False,
                'error': f'insert_product_data failed: {exc}',
                'inserted': 0
            }

        print(f"[INGEST] ✅ Inserted {result.get('inserted', 0)} products")

        return result

    def ingest_project_runs(self, project_id: int, project_token: str, days_back: int = 30) -> dict:
        """
        Ingest data from all recent completed runs of a project

        Args:
            project_id: Database project ID
            project_token: ParseHub project token
            days_back: How many days back to look for completed runs

        Returns:
            Summary of ingestion results
        """
        print(
            f"\n[INGEST] Fetching runs for project {project_token} (last {days_back} days)")

        try:
            # Get project to find all runs
            response = requests.get(
                f'{BASE_URL}/projects/{project_token}',
                params={'api_key': self.api_key},
                timeout=30
            )
            response.raise_for_status()
            project_data = response.json()

        except Exception as e:
            print(f"Error fetching project: {e}")
            return {'success': False, 'error': str(e)}

        # Process run list
        run_list = project_data.get('run_list', [])
        cutoff_date = datetime.now() - timedelta(days=days_back)

        print(f"[INGEST] Found {len(run_list)} runs total")

        total_inserted = 0
        completed_runs = 0
        skipped_runs = 0

        for run in run_list:
            run_token = run.get('run_token')
            status = run.get('status')
            start_time_str = run.get('start_time')

            # Check if run is recent
            try:
                run_time = datetime.fromisoformat(
                    start_time_str.replace('Z', '+00:00'))
                if run_time < cutoff_date:
                    skipped_runs += 1
                    continue
            except:
                pass

            # Only process complete runs
            if status != 'complete':
                skipped_runs += 1
                continue

            print(f"\n[INGEST] Processing run {run_token} (status: {status})")

            result = self.ingest_run(project_id, project_token, run_token)

            if result.get('success'):
                total_inserted += result.get('inserted', 0)
                completed_runs += 1
            else:
                skipped_runs += 1

        return {
            'success': True,
            'completed_runs': completed_runs,
            'skipped_runs': skipped_runs,
            'total_products_inserted': total_inserted
        }

    def _get_or_create_run(self, project_id: int, run_token: str, run_data: dict) -> int:
        """Get existing run record or create/update one via database abstraction."""
        try:
            existing = self.db.get_run_by_token(run_token)
            if existing and existing.get('id') is not None:
                return int(existing['id'])

            status = run_data.get('status', 'unknown')
            pages = int(run_data.get('pages') or 0)
            start_time = run_data.get('start_time')
            end_time = run_data.get('end_time')
            data_ready = bool(run_data.get('data_ready'))

            run_id = self.db.upsert_run(
                project_id=project_id,
                run_token=run_token,
                status=status,
                pages_requested=max(1, pages),
                pages_scraped=pages,
                data_ready=data_ready,
                start_time=start_time,
                end_time=end_time,
            )
            return int(run_id) if run_id is not None else None
        except Exception as e:
            print(f"Error creating run record: {e}")
            return None


def ingest_project_data(project_token: str, days_back: int = 30):
    """
    Main function to ingest data for a project by token
    """
    try:
        ingestor = ParseHubDataIngestor()

        # Get project from database
        db = get_database()
        project_id = db.get_project_id_by_token(project_token)

        if not project_id:
            print(f"❌ Project not found: {project_token}")
            return

        print(f"✅ Found project ID: {project_id}")

        # Ingest all runs
        result = ingestor.ingest_project_runs(
            project_id, project_token, days_back)

        print(f"\n{'='*60}")
        print(f"INGESTION COMPLETE")
        print(f"{'='*60}")
        print(f"Completed runs: {result.get('completed_runs', 0)}")
        print(f"Skipped runs: {result.get('skipped_runs', 0)}")
        print(
            f"Total products inserted: {result.get('total_products_inserted', 0)}")

        # Show statistics
        stats = db.get_product_data_stats(project_id)
        print(f"\nProject Statistics:")
        print(f"  Total products: {stats.get('total_products', 0)}")
        print(
            f"  Total runs with data: {stats.get('total_runs_with_data', 0)}")
        print(f"  Latest extraction: {stats.get('latest_extraction', 'N/A')}")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        project_token = sys.argv[1]
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        ingest_project_data(project_token, days)
    else:
        print(
            "Usage: python data_ingestion_service.py <project_token> [days_back=30]")
        print("\nExample:")
        print("  python data_ingestion_service.py teFu8XF3xYrj 7")
