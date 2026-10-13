from __future__ import annotations

import csv
import json
import io
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import pytz
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS


ROOT_DIR = Path(__file__).resolve().parent.parent
# Backend env source-of-truth: backend/.env only.
load_dotenv(ROOT_DIR / "backend" / ".env")

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from backend.database import get_database
    from backend.automation_service import ParseHubAutomationService
    from backend.celery_tasks import process_due_schedules
    from backend.excel_import_service import ExcelImportService
    from backend.fetch_projects import fetch_all_projects
except ImportError:
    from database import get_database
    from automation_service import ParseHubAutomationService
    from celery_tasks import process_due_schedules
    from excel_import_service import ExcelImportService
    from fetch_projects import fetch_all_projects


PARSEHUB_BASE_URL = os.getenv('PARSEHUB_BASE_URL', 'https://www.parsehub.com/api/v2')
BACKEND_API_KEY = os.getenv('BACKEND_API_KEY', '')
AUTOMATION_INTERNAL_KEY = os.getenv('AUTOMATION_INTERNAL_KEY', '')
PARSEHUB_WEBHOOK_SECRET = os.getenv('PARSEHUB_WEBHOOK_SECRET', '')

app = Flask(__name__)
CORS(app)

db = get_database()
excel_import_service = ExcelImportService(db)


class ParseHubRateLimiter:
    """Simple process-local limiter to keep ParseHub traffic conservative."""

    def __init__(self, sustained_rps: float = 2.0, burst_rps: float = 5.0):
        self.sustained_interval = 1.0 / max(0.1, sustained_rps)
        self.burst_interval = 1.0 / max(0.1, burst_rps)
        self.lock = threading.Lock()
        self.last_time = 0.0

    def wait_for_slot(self):
        while True:
            with self.lock:
                now = time.monotonic()
                min_next = max(self.last_time + self.sustained_interval, self.last_time + self.burst_interval)
                if now >= min_next:
                    self.last_time = now
                    return
                sleep_for = max(0.0, min_next - now)
            if sleep_for > 0:
                time.sleep(sleep_for)


parsehub_rate_limiter = ParseHubRateLimiter(
    sustained_rps=float(os.getenv('PARSEHUB_SUSTAINED_RPS', '2')),
    burst_rps=float(os.getenv('PARSEHUB_BURST_RPS', '5')),
)
parsehub_inflight_semaphore = threading.BoundedSemaphore(
    value=max(1, min(int(os.getenv('PARSEHUB_MAX_INFLIGHT', '4')), 16))
)


def require_auth():
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f'Bearer {BACKEND_API_KEY}':
        return jsonify({'error': 'Unauthorized'}), 401
    return None


def require_internal_auth():
    """Allow backend key or dedicated internal automation key."""
    auth_header = request.headers.get('Authorization', '')
    internal_key = request.headers.get('X-Internal-Automation-Key', '')
    if BACKEND_API_KEY and auth_header == f'Bearer {BACKEND_API_KEY}':
        return None
    if AUTOMATION_INTERNAL_KEY and internal_key == AUTOMATION_INTERNAL_KEY:
        return None
    return jsonify({'error': 'Unauthorized'}), 401


def require_webhook_auth():
    """Protect webhook receiver with shared secret token."""
    if not PARSEHUB_WEBHOOK_SECRET:
        return jsonify({'error': 'Webhook secret not configured'}), 503
    provided = request.headers.get('X-ParseHub-Webhook-Secret', '')
    if provided != PARSEHUB_WEBHOOK_SECRET:
        return jsonify({'error': 'Unauthorized webhook'}), 401
    return None


def get_parsehub_api_key() -> str:
    api_key = os.getenv('PARSEHUB_API_KEY', '').strip()
    if not api_key:
        raise RuntimeError('PARSEHUB_API_KEY is not configured')
    return api_key


def _parsehub_request(method: str, path: str, payload: dict | None = None) -> dict:
    max_attempts = max(1, int(os.getenv('PARSEHUB_RETRY_MAX_ATTEMPTS', '4')))
    backoff_base = float(os.getenv('PARSEHUB_RETRY_BACKOFF_SECONDS', '0.5'))
    timeout_seconds = int(os.getenv('PARSEHUB_TIMEOUT_SECONDS', '30'))

    for attempt in range(1, max_attempts + 1):
        parsehub_rate_limiter.wait_for_slot()
        acquired = parsehub_inflight_semaphore.acquire(timeout=timeout_seconds)
        if not acquired:
            if attempt >= max_attempts:
                raise RuntimeError('Timed out waiting for ParseHub request slot')
            time.sleep(backoff_base * (2 ** (attempt - 1)))
            continue
        try:
            if method.upper() == 'GET':
                response = requests.get(
                    f'{PARSEHUB_BASE_URL}{path}',
                    params={'api_key': get_parsehub_api_key(), **(payload or {})},
                    timeout=timeout_seconds,
                )
            else:
                response = requests.post(
                    f'{PARSEHUB_BASE_URL}{path}',
                    data={'api_key': get_parsehub_api_key(), **(payload or {})},
                    timeout=timeout_seconds,
                )

            if response.status_code in {429, 500, 502, 503, 504} and attempt < max_attempts:
                sleep_seconds = backoff_base * (2 ** (attempt - 1))
                time.sleep(sleep_seconds)
                continue

            response.raise_for_status()
            return response.json()
        except requests.RequestException:
            if attempt >= max_attempts:
                raise
            sleep_seconds = backoff_base * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)
        finally:
            parsehub_inflight_semaphore.release()

    raise RuntimeError('ParseHub request exhausted retries')


def parsehub_get(path: str, params: dict | None = None) -> dict:
    return _parsehub_request('GET', path, params)


def parsehub_post(path: str, data: dict | None = None) -> dict:
    return _parsehub_request('POST', path, data)


def normalize_text(value: str | None) -> str:
    return ' '.join((value or '').strip().lower().split())


def is_valid_http_url(value: str | None) -> bool:
    if value is None:
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    return parsed.scheme in {'http', 'https'} and bool(parsed.netloc)


def is_msa_pricing_title(title: str | None) -> bool:
    normalized = normalize_text(title)
    # Accept minor spacing variations around the closing parenthesis.
    return bool(re.match(r'^\(\s*msa\s+pricing\s*\)', normalized))


def _parse_local_schedule_to_utc(schedule_text: str, timezone_name: str | None) -> tuple[str, str]:
    """Convert local schedule input to UTC for execution while preserving local input text."""
    raw_value = str(schedule_text or '').strip()
    if not raw_value:
        raise ValueError('scheduled_run_time is required')

    normalized = raw_value.replace('Z', '+00:00')
    parsed = datetime.fromisoformat(normalized)

    if parsed.tzinfo is not None:
        utc_dt = parsed.astimezone(pytz.UTC)
        local_dt = parsed
    else:
        if not timezone_name:
            raise ValueError('timezone is required when scheduled_run_time has no timezone offset')
        try:
            tz = pytz.timezone(str(timezone_name))
        except Exception as exc:
            raise ValueError(f'invalid timezone: {timezone_name}') from exc
        local_dt = tz.localize(parsed)
        utc_dt = local_dt.astimezone(pytz.UTC)

    utc_iso = utc_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return utc_iso, raw_value


automation_service = ParseHubAutomationService(
    db=db,
    parsehub_get=parsehub_get,
    parsehub_post=parsehub_post,
    parsehub_api_key=get_parsehub_api_key,
    is_msa_title=is_msa_pricing_title,
)
automation_service.start_scheduler()


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'success': True, 'status': 'ok'}), 200


@app.route('/api/metadata', methods=['GET'])
def get_metadata():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    limit = min(max(request.args.get('limit', 100, type=int), 1), 1000)
    offset = max(request.args.get('offset', 0, type=int), 0)
    search = request.args.get('search')
    def normalize_query_values(name: str):
        values = [value.strip() for value in request.args.getlist(name) if value and value.strip()]
        if values:
            return values
        single = request.args.get(name)
        if single and single.strip():
            return single.strip()
        return None

    region = normalize_query_values('region')
    country = normalize_query_values('country')
    brand = normalize_query_values('brand')

    records = db.get_metadata_filtered(
        project_id_parsehub=request.args.get('project_id_parsehub') or request.args.get('project_token'),
        region=region,
        country=country,
        brand=brand,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = db.count_metadata_filtered(
        project_id_parsehub=request.args.get('project_id_parsehub') or request.args.get('project_token'),
        region=region,
        country=country,
        brand=brand,
        search=search,
    )
    return jsonify(
        {
            'success': True,
            'records': records,
            'count': len(records),
            'total': total,
            'limit': limit,
            'offset': offset,
        }
    ), 200


@app.route('/api/metadata', methods=['POST'])
def create_metadata():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}

    personal_project_id = str(payload.get('personal_project_id') or '').strip()
    project_name = str(payload.get('project_name') or '').strip()
    project_id_parsehub = str(payload.get('project_id_parsehub') or '').strip() or None
    last_run_data = str(payload.get('last_run_data') or '').strip() or None
    create_date = str(payload.get('create_date') or '').strip() or None
    update_date = str(payload.get('update_date') or '').strip() or None
    region = str(payload.get('region') or '').strip() or None
    country = str(payload.get('country') or '').strip() or None
    brand = str(payload.get('brand') or '').strip() or None
    website_url = str(payload.get('website_url') or '').strip() or None
    next_page_url = str(payload.get('next_page_url') or '').strip() or None
    website_type_raw = str(payload.get('website_type') or '').strip()
    website_type = website_type_raw if website_type_raw in ('Collective', 'Individual') else None

    if not personal_project_id:
        return jsonify({'success': False, 'error': 'Personal Project ID is required'}), 400
    if not project_name:
        return jsonify({'success': False, 'error': 'Project name is required'}), 400
    if website_url and not is_valid_http_url(website_url):
        return jsonify({'success': False, 'error': 'Website URL must be a valid http/https URL'}), 400
    if next_page_url and not is_valid_http_url(next_page_url):
        return jsonify({'success': False, 'error': 'Next page URL must be a valid http/https URL'}), 400

    numeric_fields = {
        'total_pages': payload.get('total_pages'),
        'total_products': payload.get('total_products'),
        'current_page_scraped': payload.get('current_page_scraped'),
        'current_product_scraped': payload.get('current_product_scraped'),
    }
    normalized_numeric: dict[str, int | None] = {}
    for field, value in numeric_fields.items():
        if value in (None, ''):
            normalized_numeric[field] = None
            continue
        try:
            parsed_value = int(value)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': f'{field} must be a non-negative integer'}), 400
        if parsed_value < 0:
            return jsonify({'success': False, 'error': f'{field} must be a non-negative integer'}), 400
        normalized_numeric[field] = parsed_value

    if db.get_metadata_by_id(personal_project_id):
        return jsonify({'success': False, 'error': f'Metadata record {personal_project_id} already exists'}), 409

    record_id = db.add_metadata_record(
        personal_project_id=personal_project_id,
        project_id_parsehub=project_id_parsehub,
        project_name=project_name,
        website_type=website_type,
        last_run_data=last_run_data,
        create_date=create_date or update_date or datetime.utcnow().isoformat(),
        update_date=update_date or datetime.utcnow().isoformat(),
        region=region,
        country=country,
        brand=brand,
        website_url=website_url,
        next_page_url=next_page_url,
        total_pages=normalized_numeric['total_pages'],
        total_products=normalized_numeric['total_products'],
        current_page_scraped=normalized_numeric['current_page_scraped'] or 0,
        current_product_scraped=normalized_numeric['current_product_scraped'] or 0,
    )

    if not record_id:
        return jsonify({'success': False, 'error': 'Failed to create metadata record'}), 500

    record = db.get_metadata_by_id(record_id)
    return jsonify({'success': True, 'record': record}), 201


@app.route('/api/metadata/<metadata_id>', methods=['GET'])
def get_metadata_by_id(metadata_id: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    record = db.get_metadata_by_id(metadata_id)
    if not record:
        return jsonify({'error': 'Metadata not found'}), 404
    return jsonify({'success': True, 'record': record}), 200


@app.route('/api/metadata/<metadata_id>', methods=['PUT'])
def update_metadata(metadata_id: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    success = db.update_metadata_record(metadata_id, payload)
    if not success:
        return jsonify({'error': 'Failed to update metadata'}), 400
    return jsonify({'success': True, 'record': db.get_metadata_by_id(metadata_id)}), 200


@app.route('/api/metadata/<metadata_id>', methods=['DELETE'])
def delete_metadata(metadata_id: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    existing = db.get_metadata_by_id(metadata_id)
    if not existing:
        return jsonify({'success': False, 'error': 'Metadata not found'}), 404

    success = db.delete_metadata_record(metadata_id)
    if not success:
        return jsonify({'success': False, 'error': 'Failed to delete metadata'}), 400
    return jsonify({'success': True, 'message': f'Metadata record {metadata_id} deleted'}), 200


@app.route('/api/metadata/sync-tokens', methods=['POST'])
def sync_metadata_tokens():
    """Populate metadata.project_id_parsehub for all rows where it is NULL.

    Matches metadata rows to projects rows by exact project_name == title
    comparison (case-insensitive). Safe to call repeatedly.
    """
    auth_error = require_auth()
    if auth_error:
        return auth_error

    result = db.backfill_metadata_project_tokens()
    return jsonify(result), 200 if result.get('success') else 500


@app.route('/api/metadata/import', methods=['POST'])
def import_metadata():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    file = request.files.get('file')
    if file is None or not file.filename:
        return jsonify({'error': 'File upload is required'}), 400

    suffix = Path(file.filename).suffix or '.csv'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        file.save(handle.name)
        temp_path = handle.name

    try:
        result = excel_import_service.bulk_import_metadata(temp_path, request.form.get('uploaded_by'))
        return jsonify(result), 200 if result.get('success') else 400
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route('/api/metadata/import-history', methods=['GET'])
def import_history():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    batches = db.get_import_batches(
        limit=min(max(request.args.get('limit', 50, type=int), 1), 500),
        offset=max(request.args.get('offset', 0, type=int), 0),
    )
    return jsonify({'success': True, 'batches': batches, 'count': len(batches)}), 200


@app.route('/api/metadata/template', methods=['GET'])
def download_metadata_template():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    csv_content = excel_import_service.get_import_template() + '\n'
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename="metadata_template.csv"'},
    )


@app.route('/api/metadata/export', methods=['GET'])
def export_metadata_csv():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    columns = db.get_metadata_schema_columns()
    rows = db.get_all_metadata_for_export()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)

    for row in rows:
        writer.writerow([row.get(column, '') for column in columns])

    csv_content = output.getvalue()
    output.close()

    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="metadata_export_{timestamp}.csv"'},
    )


@app.route('/api/filters', methods=['GET'])
def get_filters():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    return jsonify(
        {
            'success': True,
            'filters': {
                'regions': db.get_distinct_metadata_values('region'),
                'countries': db.get_distinct_metadata_values('country'),
                'brands': db.get_distinct_metadata_values('brand'),
                'websites': db.get_distinct_project_websites(),
            },
        }
    ), 200


@app.route('/api/filters/values', methods=['GET'])
def get_filter_values():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    field = request.args.get('field')
    if field not in {'region', 'country', 'brand'}:
        return jsonify({'error': 'Invalid field'}), 400
    values = db.get_distinct_metadata_values(field)
    return jsonify({'success': True, 'field': field, 'values': values, 'count': len(values)}), 200


@app.route('/api/projects/sync', methods=['POST'])
def sync_projects():
    auth_error = require_auth()
    if auth_error:
        return auth_error
    try:
        payload = request.get_json(silent=True) or {}
        relink_metadata_tokens = bool(payload.get('relink_metadata_tokens', False))
        force_overwrite = bool(payload.get('force_overwrite', False))

        projects = fetch_all_projects(get_parsehub_api_key())
        sync_result = db.sync_projects(projects)
        metadata_sync_result = None
        if relink_metadata_tokens:
            metadata_sync_result = db.sync_metadata_with_projects(projects, force_overwrite=force_overwrite)
        return jsonify(
            {
                'success': True,
                'message': f'Synced {len(projects)} projects',
                'total': len(projects),
                'sync_result': sync_result,
                'metadata_sync_result': metadata_sync_result,
                'metadata_relink_triggered': relink_metadata_tokens,
            }
        ), 200
    except requests.RequestException as exc:
        return jsonify({'success': False, 'error': f'ParseHub sync failed: {str(exc)}'}), 502
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Project sync failed: {str(exc)}'}), 500


@app.route('/api/projects/sync-msa', methods=['POST'])
def sync_projects_msa():
    auth_error = require_auth()
    if auth_error:
        return auth_error
    try:
        payload = request.get_json(silent=True) or {}
        page = max(int(payload.get('page', 1)), 1)
        limit = min(max(int(payload.get('limit', 200)), 1), 1000)
        def normalize_filter_values(raw_value):
            if raw_value is None:
                return None
            if isinstance(raw_value, list):
                cleaned = [str(item).strip() for item in raw_value if str(item).strip()]
                return cleaned or None
            normalized = str(raw_value).strip()
            return normalized or None

        region = normalize_filter_values(payload.get('region'))
        country = normalize_filter_values(payload.get('country'))
        brand = normalize_filter_values(payload.get('brand'))
        website = normalize_filter_values(payload.get('website'))

        sync_state = automation_service.sync_msa_projects(trigger='manual_api')
        if not sync_state.get('success'):
            return jsonify({'success': False, 'error': sync_state.get('error', 'MSA sync failed')}), 500

        # Query only MSA-prefixed rows directly from DB with real pagination.
        # This avoids scanning thousands of rows in Python on every dashboard load.
        listed = db.list_projects(
            page=page,
            limit=limit,
            region=region,
            country=country,
            brand=brand,
            website=website,
            filter_keyword=None,
        )
        msa_listed_projects = [
            project for project in listed.get('projects', []) if is_msa_pricing_title(project.get('title') or project.get('name'))
        ]
        offset = (page - 1) * limit
        page_projects = msa_listed_projects[offset: offset + limit]
        total = len(msa_listed_projects)

        return jsonify(
            {
                'success': True,
                'message': f"Synced {sync_state.get('parsehub_msa_projects', 0)} MSA projects",
                'parsehub_total_projects': sync_state.get('parsehub_total_projects', 0),
                'parsehub_msa_projects': sync_state.get('parsehub_msa_projects', 0),
                'sync_result': sync_state.get('sync_result', {}),
                'metadata_sync_result': None,
                'metadata_relink_triggered': False,
                'projects': page_projects,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'total_pages': (total + limit - 1) // limit if limit else 1,
                    'has_more': offset + limit < total,
                },
            }
        ), 200
    except requests.RequestException as exc:
        return jsonify({'success': False, 'error': f'ParseHub sync failed: {str(exc)}'}), 502
    except Exception as exc:
        return jsonify({'success': False, 'error': f'MSA project sync failed: {str(exc)}'}), 500


@app.route('/api/projects', methods=['GET'])
def get_projects():
    auth_error = require_auth()
    if auth_error:
        return auth_error
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 50, type=int), 1), 1000)
        filter_keyword = request.args.get('filter_keyword')

        def normalize_query_values(name: str):
            values = [value.strip() for value in request.args.getlist(name) if value and value.strip()]
            if values:
                return values
            single = request.args.get(name)
            if single and single.strip():
                return single.strip()
            return None

        region = normalize_query_values('region')
        country = normalize_query_values('country')
        brand = normalize_query_values('brand')
        website = normalize_query_values('website')

        # Keep MSA filtering logic identical to /api/projects/sync-msa so counts match.
        # SQL LIKE "(msa pricing)" can miss titles that pass the regex-based prefix matcher.
        if normalize_text(filter_keyword) == '(msa pricing)':
            listed = db.list_projects(
                page=1,
                limit=5000,
                region=region,
                country=country,
                brand=brand,
                website=website,
                filter_keyword=None,
            )
            msa_projects = [
                project for project in listed.get('projects', [])
                if is_msa_pricing_title(project.get('title') or project.get('name'))
            ]
            offset = (page - 1) * limit
            page_projects = msa_projects[offset: offset + limit]
            result = {
                'success': True,
                'projects': page_projects,
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': len(msa_projects),
                    'total_pages': (len(msa_projects) + limit - 1) // limit if limit else 1,
                    'has_more': offset + limit < len(msa_projects),
                },
            }
        else:
            result = db.list_projects(
                page=page,
                limit=limit,
                region=region,
                country=country,
                brand=brand,
                website=website,
                filter_keyword=filter_keyword,
            )
        return jsonify(result), 200
    except Exception as exc:
        return jsonify({'success': False, 'error': f'Failed to list projects: {str(exc)}'}), 500


@app.route('/api/projects/<token>', methods=['GET'])
def get_project(token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    project = db.get_project_by_token(token)
    if not project:
        return jsonify({'error': 'Project not found', 'success': False}), 404

    latest_ingestion = db.get_latest_run_ingestion_by_project(project['id'])
    active_runs = db.get_runs_by_project(project['id'], limit=10)
    has_active_run = any((run.get('status') in {'initialized', 'running', 'queued'}) for run in active_runs)
    project['automation_state'] = {
        'automation_enabled': automation_service.enabled,
        'scheduler_enabled': automation_service.scheduler_enabled,
        'in_automated_progression': has_active_run,
        'latest_ingestion': latest_ingestion,
        'last_automation_event_at': (latest_ingestion or {}).get('updated_at'),
    }
    return jsonify({'success': True, 'data': project}), 200


@app.route('/api/projects/<token>/run', methods=['POST'])
def run_project(token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    project = db.get_project_by_token(token)
    if not project:
        return jsonify({'error': 'Project not found'}), 404

    project_lock_key = f"project:{project['id']}:manual-run"
    lock_owner = f"manual-run:{datetime.utcnow().isoformat()}"
    if not db.acquire_automation_lock(project_lock_key, lock_owner, ttl_seconds=120):
        return jsonify({'error': 'Another run action is already in progress for this project. Retry shortly.'}), 409

    try:
        latest_runs = db.get_runs_by_project(project['id'], limit=10)
        if any((run.get('status') in {'initialized', 'running', 'queued'}) for run in latest_runs):
            return jsonify({'error': 'Project already has an active run. Wait for completion before starting another run.'}), 409

        run_info = parsehub_post(f'/projects/{token}/run')
        run_token = run_info.get('run_token')
        if not run_token:
            return jsonify({'error': 'ParseHub did not return a run token'}), 502

        # Diagnostic: log every manual run trigger with caller context
        print(
            f'[RUN-TRIGGER] source=manual_api token={token} run_token={run_token}',
            flush=True,
        )

        # Guard against ParseHub returning the same run token for duplicate triggers.
        existing_run = db.get_run_by_token(run_token)
        if existing_run and existing_run.get('project_id') == project['id']:
            existing_cumulative_id = existing_run.get('project_run_cumulative_id')
            db.add_automation_audit_event(
                event_type='manual.run_blocked_duplicate_token',
                project_id=project['id'],
                project_token=token,
                run_token=run_token,
                project_run_cumulative_id=existing_cumulative_id,
                status='blocked',
                message='Manual run rejected because ParseHub returned an existing active run token',
            )
            return jsonify(
                {
                    'error': 'Project already has an active run token from ParseHub.',
                    'run_token': run_token,
                    'project_run_cumulative_id': existing_cumulative_id,
                }
            ), 409

        # Fresh manual Run rotates the cumulative session, so wipe any per-session
        # progress carried over from a previously completed session before we attach
        # the new run. Without this reset:
        #   - completion progress over-counts (e.g. 22/21 during the run).
        #   - resume status sees stale current_page_scraped == total_pages and reports
        #     project_complete, suppressing auto-resume.
        db.reset_project_progress_for_new_session(project['id'])

        # Fresh manual Run always creates (or rotates to) a new cumulative session.
        project_run_cumulative_id = db.attach_run_to_cumulative_session(
            project_id=project['id'],
            project_token=token,
            run_token=run_token,
            force_new_session=True,
        )

        db.upsert_run(
            project['id'],
            run_token,
            run_info.get('status', 'running'),
            pages_requested=1,
            pages_scraped=0,
            data_ready=False,
            start_time=run_info.get('start_time'),
            project_run_cumulative_id=project_run_cumulative_id,
        )

        db.add_automation_audit_event(
            event_type='manual.run_started',
            project_id=project['id'],
            project_token=token,
            run_token=run_token,
            project_run_cumulative_id=project_run_cumulative_id,
            status='ok',
            message='Manual run started',
        )
    finally:
        db.release_automation_lock(project_lock_key, lock_owner)

    metadata = project.get('metadata') or {}
    personal_project_id = metadata.get('personal_project_id')
    if personal_project_id:
        db.update_metadata_progress(
            str(personal_project_id),
            last_run_data=run_info.get('start_time'),
            update_date=run_info.get('start_time') or None,
        )

    return jsonify(
        {
            'success': True,
            'run_token': run_token,
            'status': run_info.get('status', 'running'),
            'project_run_cumulative_id': project_run_cumulative_id,
        }
    ), 200


@app.route('/api/schedule-project', methods=['POST'])
def schedule_project_run():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    project_token = str(payload.get('project_token') or payload.get('token') or '').strip()
    schedule_type = str(payload.get('schedule_type') or 'one_time').strip().lower()
    scheduled_run_time = payload.get('scheduled_run_time')
    timezone_name = str(payload.get('timezone') or '').strip() or None

    recurrence_payload = payload.get('recurrence') if isinstance(payload.get('recurrence'), dict) else {}
    recurrence_frequency = str(
        recurrence_payload.get('frequency')
        or payload.get('recurrence_frequency')
        or ''
    ).strip().lower() or None
    recurrence_weekday_raw = recurrence_payload.get('weekday', payload.get('recurrence_weekday'))
    recurrence_day_raw = recurrence_payload.get('day_of_month', payload.get('recurrence_day_of_month'))
    local_time = str(recurrence_payload.get('local_time') or payload.get('local_time') or '').strip() or None

    if not project_token:
        return jsonify({'success': False, 'error': 'project_token is required'}), 400

    project = db.get_project_by_token(project_token)
    if not project:
        return jsonify({'success': False, 'error': 'Project not found'}), 404

    recurrence_weekday = None
    recurrence_day_of_month = None

    if schedule_type == 'recurring':
        if not timezone_name:
            return jsonify({'success': False, 'error': 'timezone is required for recurring schedules'}), 400
        if not recurrence_frequency:
            return jsonify({'success': False, 'error': 'recurrence.frequency is required for recurring schedules'}), 400
        if not local_time:
            return jsonify({'success': False, 'error': 'recurrence.local_time is required for recurring schedules'}), 400

        if recurrence_frequency == 'weekly':
            try:
                recurrence_weekday = int(recurrence_weekday_raw)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'recurrence.weekday must be 0-6 for weekly schedules'}), 400
            if recurrence_weekday < 0 or recurrence_weekday > 6:
                return jsonify({'success': False, 'error': 'recurrence.weekday must be between 0 and 6'}), 400
        elif recurrence_frequency == 'monthly':
            try:
                recurrence_day_of_month = int(recurrence_day_raw)
            except (TypeError, ValueError):
                return jsonify({'success': False, 'error': 'recurrence.day_of_month must be 1-31 for monthly schedules'}), 400
            if recurrence_day_of_month < 1 or recurrence_day_of_month > 31:
                return jsonify({'success': False, 'error': 'recurrence.day_of_month must be between 1 and 31'}), 400
        elif recurrence_frequency != 'daily':
            return jsonify({'success': False, 'error': 'recurrence.frequency must be daily, weekly, or monthly'}), 400

        # For recurring schedules, DB computes first next-run UTC from rule + timezone.
        utc_iso = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        local_input_value = None
    else:
        schedule_type = 'one_time'
        try:
            utc_iso, local_input_value = _parse_local_schedule_to_utc(str(scheduled_run_time or ''), timezone_name)
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        if utc_iso <= now_utc:
            return jsonify({'success': False, 'error': 'scheduled_run_time must be in the future'}), 400

    try:
        created = db.create_project_schedule(
            project_token=project_token,
            scheduled_run_time_utc=utc_iso,
            scheduled_run_time_local=local_input_value,
            timezone=timezone_name,
            schedule_type=schedule_type,
            recurrence_frequency=recurrence_frequency,
            recurrence_weekday=recurrence_weekday,
            recurrence_day_of_month=recurrence_day_of_month,
            local_time=local_time,
        )
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400

    if not created:
        return jsonify({'success': False, 'error': 'Failed to create schedule'}), 500

    db.add_automation_audit_event(
        event_type='manual.project_scheduled',
        project_id=project['id'],
        project_token=project_token,
        status='ok',
        message='Project run scheduled',
        details={
            'schedule_id': created.get('id'),
            'schedule_type': created.get('schedule_type', schedule_type),
            'recurrence_frequency': created.get('recurrence_frequency'),
            'recurrence_weekday': created.get('recurrence_weekday'),
            'recurrence_day_of_month': created.get('recurrence_day_of_month'),
            'local_time': created.get('local_time'),
            'scheduled_run_time_utc': created.get('scheduled_run_time_utc'),
            'scheduled_run_time_local': created.get('scheduled_run_time_local'),
            'timezone': created.get('timezone'),
        },
    )

    return jsonify(
        {
            'success': True,
            'message': 'Project scheduled successfully',
            'schedule': created,
        }
    ), 200


@app.route('/api/schedule-run', methods=['POST'])
def schedule_run_alias():
    return schedule_project_run()


@app.route('/api/scheduled-runs', methods=['GET'])
def get_scheduled_runs():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    # Keep statuses aligned with live/local run state before returning data.
    db.refresh_scheduled_run_statuses_from_runs()

    project_token = request.args.get('project_token')
    include_all = str(request.args.get('include_all', 'false')).strip().lower() in {'1', 'true', 'yes'}
    requested_status = str(request.args.get('status', '')).strip()
    requested_schedule_type = str(request.args.get('schedule_type', '')).strip()
    limit = min(max(request.args.get('limit', 200, type=int), 1), 1000)
    status_filter = None if include_all else (requested_status if requested_status and requested_status.lower() != 'all' else 'Scheduled')
    schedule_type_filter = requested_schedule_type if requested_schedule_type and requested_schedule_type.lower() != 'all' else None
    runs = db.get_scheduled_runs(
        project_token=project_token,
        limit=limit,
        status=status_filter,
        schedule_type=schedule_type_filter,
    )
    return jsonify({'success': True, 'count': len(runs), 'data': runs}), 200


@app.route('/api/scheduled-runs/<int:schedule_id>', methods=['DELETE'])
def delete_scheduled_run(schedule_id: int):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    deleted = db.delete_scheduled_run(schedule_id)
    if not deleted:
        return jsonify({'success': False, 'error': 'Scheduled run not found'}), 404

    return jsonify({'success': True, 'message': 'Scheduled run deleted'}), 200


@app.route('/api/scheduled-runs/trigger', methods=['POST'])
def trigger_scheduled_runs():
    auth_error = require_auth()
    if auth_error:
        return auth_error

    try:
        result = process_due_schedules()
        return jsonify({'success': True, 'result': result}), 200
    except Exception as exc:  # noqa: BLE001
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route('/api/projects/<token>/resume-status', methods=['GET'])
def get_resume_status(token: str):
    """Get comprehensive resume status without triggering a resume.
    
    Calculates max scraped page from actual product data and compares to metadata.total_pages.
    Determines if project is resumable and generates next_page_url if safe to do so.
    """
    auth_error = require_auth()
    if auth_error:
        return auth_error

    status = db.prepare_resume_status(token)

    # If the active cumulative session has reached completion, close it.
    if status.get('success') and status.get('project_complete') and status.get('project_id'):
        db.close_latest_active_cumulative_session(int(status['project_id']))

    http_code = 200 if status['success'] else 400
    return jsonify(status), http_code


@app.route('/api/projects/<token>/resume', methods=['POST'])
def resume_project(token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    # 1. Prepare resume status (get max scraped page, compare to total_pages, generate URL)
    status = db.prepare_resume_status(token)
    if not status['success']:
        return jsonify({'success': False, 'error': status.get('error', 'Failed to prepare resume'), 'message': status.get('message')}), 400

    project_id = status['project_id']
    project_lock_key = f'project:{project_id}:manual-resume'
    lock_owner = f"manual-resume:{datetime.utcnow().isoformat()}"
    if not db.acquire_automation_lock(project_lock_key, lock_owner, ttl_seconds=120):
        return jsonify({'success': False, 'error': 'Another resume action is already in progress for this project'}), 409

    try:
        # 2. Check if project is complete
        if status['project_complete']:
            if status.get('project_id'):
                db.close_latest_active_cumulative_session(int(status['project_id']))
            return jsonify({'success': False, 'error': 'Project is complete', 'message': status['message']}), 400

        # 3. Check if project is resumable
        if not status['resumable']:
            return jsonify({'success': False, 'error': 'Project cannot be resumed', 'message': status['message']}), 400

        latest_runs = db.get_runs_by_project(project_id, limit=10)
        if any((run.get('status') in {'initialized', 'running', 'queued'}) for run in latest_runs):
            return jsonify({'success': False, 'error': 'Project already has an active run', 'message': 'Wait for current run to complete before resuming.'}), 409

        metadata = status['metadata']
        max_page_scraped = status['max_page_scraped'] or 0
        total_pages = status['total_pages']
        next_page_number = status['next_page_number']
        generated_url = status['generated_next_page_url']
        project_run_cumulative_id = status.get('active_project_run_cumulative_id')

        if not project_run_cumulative_id:
            return jsonify({'success': False, 'error': 'No active cumulative session', 'message': 'Start a new manual Run first.'}), 400

        # 4. Update metadata with generated next_page_url if we have one
        personal_project_id = str(metadata.get('personal_project_id')) if metadata else None
        if personal_project_id and generated_url:
            db.update_metadata_progress(
                personal_project_id,
                next_page_url=generated_url,
            )

        # 5. Calculate pages to request and construct ParseHub run payload
        pages_remaining = total_pages - max_page_scraped
        run_payload = {'pages': pages_remaining}
        if generated_url:
            run_payload['start_url'] = generated_url

        run_info = parsehub_post(f'/projects/{token}/run', run_payload)
        run_token = run_info.get('run_token')
        if not run_token:
            return jsonify({'error': 'ParseHub did not return a run token'}), 502

        # 6. Immediately verify the created run object so we can confirm what ParseHub accepted.
        run_details = parsehub_get(f'/runs/{run_token}')
        parsehub_run_start_url = run_details.get('start_url') or run_info.get('start_url')
        parsehub_run_start_template = run_details.get('start_template') or run_info.get('start_template')
        start_url_honored = (not generated_url) or (parsehub_run_start_url == generated_url)

        # 7. Store run in database
        db.upsert_run(
            project_id,
            run_token,
            run_info.get('status', 'running'),
            pages_requested=pages_remaining,
            pages_scraped=0,
            data_ready=False,
            start_time=run_info.get('start_time'),
            project_run_cumulative_id=project_run_cumulative_id,
        )

        # Resume reuses the currently active cumulative id.
        db.attach_run_to_cumulative_session(
            project_id=project_id,
            project_token=token,
            run_token=run_token,
            force_new_session=False,
        )

        # 8. Update metadata progress
        if personal_project_id:
            db.update_metadata_progress(
                personal_project_id,
                current_page_scraped=max_page_scraped,
                last_run_data=run_info.get('start_time'),
                update_date=run_info.get('start_time') or None,
            )

        db.add_automation_audit_event(
            event_type='manual.resume_started',
            project_id=project_id,
            project_token=token,
            run_token=run_token,
            project_run_cumulative_id=project_run_cumulative_id,
            status='ok',
            message='Manual resume started',
            details={'next_page': next_page_number, 'pages_remaining': pages_remaining},
        )

        return jsonify(
            {
                'success': True,
                'run_token': run_token,
                'status': run_info.get('status', 'running'),
                'resume': {
                    'max_page_scraped': max_page_scraped,
                    'total_pages': total_pages,
                    'next_page': next_page_number,
                    'pages_remaining': pages_remaining,
                    'resumed_from_url': generated_url,
                    'generated_next_page_url': generated_url,
                    'requested_resume_url': generated_url,
                    'parsehub_run_start_url': parsehub_run_start_url,
                    'parsehub_run_start_template': parsehub_run_start_template,
                    'start_url_honored': start_url_honored,
                    'message': status['message'],
                    'project_run_cumulative_id': project_run_cumulative_id,
                },
                'parsehub_request': {
                    'endpoint': f'/projects/{token}/run',
                    'method': 'POST',
                    'encoding': 'application/x-www-form-urlencoded',
                    'payload': run_payload,
                },
                'parsehub_run_verification': {
                    'run_token': run_token,
                    'start_url': parsehub_run_start_url,
                    'start_template': parsehub_run_start_template,
                    'start_url_honored': start_url_honored,
                },
            }
        ), 200
    finally:
        db.release_automation_lock(project_lock_key, lock_owner)


@app.route('/api/runs/<run_token>', methods=['GET'])
def get_run_status(run_token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    existing_run = db.get_run_by_token(run_token)
    run_data = parsehub_get(f'/runs/{run_token}')
    pages_scraped = run_data.get('pages', 0) or 0
    data_ready = bool(run_data.get('data_ready'))
    if existing_run:
        db.upsert_run(
            existing_run['project_id'],
            run_token,
            run_data.get('status', existing_run['status']),
            pages_requested=existing_run.get('pages_requested') or 1,
            pages_scraped=pages_scraped,
            data_ready=data_ready,
            start_time=run_data.get('start_time') or existing_run.get('start_time'),
            end_time=run_data.get('end_time') or existing_run.get('end_time'),
        )

    # Keep scheduled run status lifecycle in sync with observed run state.
    db.refresh_scheduled_run_statuses_from_runs()
    updated_run = db.get_run_by_token(run_token)

    if updated_run:
        project_token = updated_run.get('project_token')
        metadata = db.get_metadata_by_project_token(project_token) if project_token else None
        if metadata:
            existing_page_progress = int(metadata.get('current_page_scraped') or 0)
            run_page_progress = int(pages_scraped or 0)
            total_pages_cap = int(metadata.get('total_pages') or 0)
            normalized_status = str(run_data.get('status') or '').strip().lower()
            is_terminal_success = normalized_status in {'complete', 'completed', 'success', 'succeeded'}
            # Avoid inflating confirmed progress while a run is still live; completion_progress
            # already adds live pages separately.
            next_page_progress = existing_page_progress
            if data_ready and is_terminal_success:
                next_page_progress = max(existing_page_progress, run_page_progress)
                if total_pages_cap > 0:
                    next_page_progress = min(next_page_progress, total_pages_cap)
            db.update_metadata_progress(
                str(metadata.get('personal_project_id')),
                current_page_scraped=next_page_progress,
                last_run_data=run_data.get('end_time') or run_data.get('start_time'),
                update_date=run_data.get('end_time') or run_data.get('start_time'),
            )

    return jsonify(
        {
            'success': True,
            'run': {
                'run_token': run_token,
                'status': run_data.get('status'),
                'pages_scraped': pages_scraped,
                'data_ready': data_ready,
                'start_time': run_data.get('start_time'),
                'end_time': run_data.get('end_time'),
                'project_token': updated_run.get('project_token') if updated_run else None,
                'project_title': updated_run.get('project_title') if updated_run else None,
            },
        }
    ), 200


@app.route('/api/runs/<run_token>/cancel', methods=['POST'])
def cancel_run(run_token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    result = parsehub_post(f'/runs/{run_token}/cancel')
    db.update_run_status(run_token, 'cancelled')
    return jsonify({'success': True, 'run_token': run_token, 'result': result}), 200


@app.route('/api/ingest/<project_token>', methods=['POST'])
def ingest_project_data(project_token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    try:
        from backend.data_ingestion_service import ParseHubDataIngestor
    except ImportError:
        from data_ingestion_service import ParseHubDataIngestor

    project_id = db.get_project_id_by_token(project_token)
    if project_id is None:
        return jsonify({'error': 'Project not found'}), 404

    payload = request.get_json(silent=True) or {}
    run_token = payload.get('run_token')
    ingestor = ParseHubDataIngestor()

    if run_token:
        run_record = db.get_run_by_token(run_token)
        if not run_record:
            return jsonify({'error': 'Run not found'}), 404
        project_run_cumulative_id = run_record.get('project_run_cumulative_id')
        if not project_run_cumulative_id:
            project_run_cumulative_id = db.attach_run_to_cumulative_session(
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                force_new_session=False,
            )
            db.upsert_run(
                project_id,
                run_token,
                run_record.get('status', 'unknown'),
                pages_requested=run_record.get('pages_requested') or 1,
                pages_scraped=run_record.get('pages_scraped') or 0,
                data_ready=bool(run_record.get('data_ready')),
                start_time=run_record.get('start_time'),
                end_time=run_record.get('end_time'),
                project_run_cumulative_id=project_run_cumulative_id,
            )
        result = ingestor.ingest_run(project_id, project_token, run_token, project_run_cumulative_id)
    else:
        result = ingestor.ingest_project_runs(project_id, project_token, max(int(payload.get('days_back', 30)), 1))

    metadata = db.get_metadata_by_project_token(project_token)
    total_products = db.get_product_data_stats(project_id).get('total_products', 0)
    if metadata:
        db.update_metadata_progress(
            str(metadata.get('personal_project_id')),
            current_product_scraped=int(total_products),
        )

    completion_state = db.prepare_resume_status(project_token)
    cumulative_close = {'success': True, 'closed': False, 'project_run_cumulative_id': None}
    if completion_state.get('success') and completion_state.get('project_complete'):
        cumulative_close = db.close_latest_active_cumulative_session(project_id)

    latest_session = db.get_latest_preferred_cumulative_session(project_id)
    return jsonify(
        {
            'success': result.get('success', False),
            'ingestion_result': result,
            'statistics': db.get_product_data_stats(project_id),
            'current_cumulative_session': latest_session,
            'cumulative_session_closed': cumulative_close,
        }
    ), 200


@app.route('/api/internal/automation/status', methods=['GET'])
def get_automation_status():
    auth_error = require_internal_auth()
    if auth_error:
        return auth_error

    return jsonify(
        {
            'success': True,
            'automation_enabled': automation_service.enabled,
            'scheduler_enabled': automation_service.scheduler_enabled,
            'scheduler_running': bool(automation_service.scheduler.running),
            'resume_enabled': automation_service.resume_enabled,
            'sync_interval_minutes': automation_service.sync_minutes,
            'reconcile_interval_seconds': automation_service.reconcile_seconds,
            'max_workers': automation_service.max_workers,
            'status_workers': automation_service.status_workers,
            'ingest_workers': automation_service.ingest_workers,
            'resume_workers': automation_service.resume_workers,
        }
    ), 200


@app.route('/api/internal/automation/sync-msa', methods=['POST'])
def trigger_internal_sync_msa():
    auth_error = require_internal_auth()
    if auth_error:
        return auth_error

    state = automation_service.sync_msa_projects(trigger='internal_api')
    http_code = 200 if state.get('success') else 500
    return jsonify(state), http_code


@app.route('/api/internal/automation/reconcile-active-runs', methods=['POST'])
def trigger_internal_reconcile_active_runs():
    auth_error = require_internal_auth()
    if auth_error:
        return auth_error

    state = automation_service.reconcile_active_runs(trigger='internal_api')
    http_code = 200 if state.get('success') else 500
    return jsonify(state), http_code


@app.route('/api/internal/parsehub/webhook', methods=['POST'])
def handle_parsehub_webhook():
    auth_error = require_webhook_auth()
    if auth_error:
        return auth_error

    payload = request.get_json(silent=True) or {}
    run_token = payload.get('run_token') or payload.get('run') or payload.get('token')

    if not run_token:
        db.add_automation_audit_event(
            event_type='automation.webhook.received',
            status='ignored',
            message='Webhook payload missing run token',
            details={'payload_keys': sorted(payload.keys())[:20]},
        )
        return jsonify({'success': True, 'accepted': False, 'reason': 'missing run token'}), 202

    state = automation_service.reconcile_run_by_token(str(run_token), source='webhook')
    db.add_automation_audit_event(
        event_type='automation.webhook.received',
        run_token=str(run_token),
        status='ok' if state.get('success') else 'error',
        message='Webhook processed',
        details={'result': state},
    )
    return jsonify({'success': True, 'accepted': True, 'result': state}), 202


@app.route('/api/products/<int:project_id>', methods=['GET'])
def get_products(project_id: int):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    limit = min(max(request.args.get('limit', 100, type=int), 1), 5000)
    offset = max(request.args.get('offset', 0, type=int), 0)
    cumulative_id = request.args.get('project_run_cumulative_id')
    latest_only = request.args.get('latest_only', '1') != '0'
    data = db.get_product_data_by_project(
        project_id,
        limit=limit,
        offset=offset,
        cumulative_id=cumulative_id,
        latest_cumulative_only=latest_only,
    )
    session = db.get_latest_preferred_cumulative_session(project_id)
    return jsonify(
        {
            'success': True,
            'count': len(data),
            'limit': limit,
            'offset': offset,
            'data': data,
            'current_cumulative_session': session,
        }
    ), 200


@app.route('/api/products/run/<run_token>', methods=['GET'])
def get_products_by_run(run_token: str):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    limit = min(max(request.args.get('limit', 1000, type=int), 1), 5000)
    data = db.get_product_data_by_run(run_token, limit=limit)
    return jsonify({'success': True, 'count': len(data), 'run_token': run_token, 'data': data}), 200


@app.route('/api/products/<int:project_id>/stats', methods=['GET'])
def get_product_stats(project_id: int):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    cumulative_id = request.args.get('project_run_cumulative_id')
    latest_only = request.args.get('latest_only', '1') != '0'
    return jsonify(
        {
            'success': True,
            'project_id': project_id,
            'statistics': db.get_product_data_stats(
                project_id,
                cumulative_id=cumulative_id,
                latest_cumulative_only=latest_only,
            ),
            'current_cumulative_session': db.get_latest_preferred_cumulative_session(project_id),
        }
    ), 200


@app.route('/api/products/<int:project_id>/cumulative-stats', methods=['GET'])
def get_cumulative_stats(project_id: int):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    return jsonify(
        {
            'success': True,
            'project_id': project_id,
            'current_cumulative_session': db.get_latest_preferred_cumulative_session(project_id),
            'groups': db.get_cumulative_grouped_stats(project_id),
        }
    ), 200


@app.route('/api/products/<int:project_id>/export', methods=['GET'])
def export_products(project_id: int):
    auth_error = require_auth()
    if auth_error:
        return auth_error

    cumulative_id = request.args.get('project_run_cumulative_id') or None
    latest_only = request.args.get('latest_only', '').lower() in ('1', 'true')
    records = db.get_product_data_by_project(
        project_id,
        limit=500000,
        offset=0,
        cumulative_id=cumulative_id,
        latest_cumulative_only=latest_only,
    )
    if not records:
        return jsonify({'error': 'No data to export'}), 404

    allowed_columns = [
        'brand',
        'case_unit_price',
        'country',
        'currency',
        'extraction_date',
        'list_price',
        'product_name',
        'page_number',
        'part_number',
        'product_url',
        'sale_price',
    ]

    normalized_records = []
    for record in records:
        normalized_records.append(
            {
                'brand': record.get('brand'),
                'case_unit_price': record.get('case_unit_price'),
                'country': record.get('country'),
                'currency': record.get('currency'),
                'extraction_date': record.get('extraction_date'),
                'list_price': record.get('list_price'),
                'product_name': record.get('name') or record.get('product_name'),
                'page_number': record.get('page_number'),
                'part_number': record.get('part_number'),
                'product_url': record.get('product_url'),
                'sale_price': record.get('sale_price'),
            }
        )

    export_format = request.args.get('format', 'csv').lower()
    if export_format == 'json':
        return app.response_class(
            response=json.dumps(normalized_records, ensure_ascii=False, indent=2),
            status=200,
            mimetype='application/json',
            headers={'Content-Disposition': f'attachment; filename="project_{project_id}.json"'},
        )

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=allowed_columns, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(normalized_records)
    csv_content = output.getvalue()
    output.close()

    return Response(
        csv_content,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="project_{project_id}.csv"'},
    )


if __name__ == '__main__':
    port = int(os.getenv('BACKEND_PORT', '5001'))
    print(f"Starting backend server on port {os.getenv('BACKEND_PORT')}")
    app.run(host='0.0.0.0', port=port, debug=True)
