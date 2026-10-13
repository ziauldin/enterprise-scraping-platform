import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler

try:
    from backend.data_ingestion_service import ParseHubDataIngestor
    from backend.fetch_projects import fetch_all_projects
except ImportError:
    from data_ingestion_service import ParseHubDataIngestor
    from fetch_projects import fetch_all_projects


class ParseHubAutomationService:
    def __init__(
        self,
        db,
        parsehub_get: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        parsehub_post: Callable[[str, dict[str, Any] | None], dict[str, Any]],
        parsehub_api_key: Callable[[], str],
        is_msa_title: Callable[[str | None], bool],
    ):
        self.db = db
        self.parsehub_get = parsehub_get
        self.parsehub_post = parsehub_post
        self.parsehub_api_key = parsehub_api_key
        self.is_msa_title = is_msa_title

        self.enabled = os.getenv('AUTOMATION_ENABLED', '1').strip().lower() in {'1', 'true', 'yes'}
        self.scheduler_enabled = os.getenv('AUTOMATION_SCHEDULER_ENABLED', '1').strip().lower() in {'1', 'true', 'yes'}

        # SAFETY GATE: auto-resume starts a new ParseHub run automatically after each page completes.
        # This is OFF by default.  Set AUTOMATION_RESUME_ENABLED=1 only if you explicitly want
        # the system to continue paginated scrapes without any user action.
        self.resume_enabled = os.getenv('AUTOMATION_RESUME_ENABLED', '0').strip().lower() in {'1', 'true', 'yes'}

        self.max_workers = max(1, min(int(os.getenv('AUTOMATION_MAX_WORKERS', '4')), 8))
        self.status_workers = max(1, min(int(os.getenv('AUTOMATION_STATUS_WORKERS', '4')), 8))
        self.ingest_workers = max(1, min(int(os.getenv('AUTOMATION_INGEST_WORKERS', '3')), 8))
        self.resume_workers = max(1, min(int(os.getenv('AUTOMATION_RESUME_WORKERS', '2')), 8))

        self.reconcile_limit = max(1, min(int(os.getenv('AUTOMATION_RECONCILE_LIMIT', '40')), 500))
        self.sync_minutes = max(1, int(os.getenv('AUTOMATION_SYNC_MSA_MINUTES', '5')))
        self.reconcile_seconds = max(30, int(os.getenv('AUTOMATION_RECONCILE_SECONDS', '60')))
        self.sync_min_interval_seconds = max(0, int(os.getenv('AUTOMATION_SYNC_MIN_INTERVAL_SECONDS', '30')))
        self._sync_msa_state_lock = threading.Lock()
        self._sync_msa_local_lock = threading.Lock()
        self._last_sync_msa_completed_at_monotonic = 0.0
        self._last_sync_msa_result: dict[str, Any] | None = None

        self.scheduler = BackgroundScheduler(daemon=True)
        self._started = False
        self._start_lock = threading.Lock()

    def start_scheduler(self) -> bool:
        if not self.enabled or not self.scheduler_enabled:
            return False
        with self._start_lock:
            if self._started:
                return True

            self.scheduler.add_job(
                self.scheduled_sync_msa,
                trigger='interval',
                minutes=self.sync_minutes,
                id='sync_msa_every_5m',
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.add_job(
                self.scheduled_reconcile_active_runs,
                trigger='interval',
                seconds=self.reconcile_seconds,
                id='reconcile_active_runs',
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            self.scheduler.start()
            self._started = True
            self.db.add_automation_audit_event(
                event_type='automation.scheduler.started',
                status='ok',
                message='Automation scheduler started',
                details={
                    'sync_minutes': self.sync_minutes,
                    'reconcile_seconds': self.reconcile_seconds,
                    'max_workers': self.max_workers,
                },
            )
            return True

    def scheduled_sync_msa(self):
        self.sync_msa_projects(trigger='scheduler')

    def scheduled_reconcile_active_runs(self):
        self.reconcile_active_runs(trigger='scheduler')

    def _add_audit_event_async(self, **kwargs: Any) -> None:
        """Best-effort async audit logging for latency-sensitive endpoints."""
        def _worker():
            try:
                self.db.add_automation_audit_event(**kwargs)
            except Exception:
                # Audit should never block primary API flows.
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def sync_msa_projects(self, trigger: str = 'manual') -> dict[str, Any]:
        if not self.enabled:
            return {'success': False, 'error': 'Automation disabled'}

        if trigger in {'manual_api', 'internal_api', 'manual'} and self.sync_min_interval_seconds > 0:
            with self._sync_msa_state_lock:
                elapsed_since_last = time.monotonic() - self._last_sync_msa_completed_at_monotonic
                if self._last_sync_msa_completed_at_monotonic > 0 and elapsed_since_last < self.sync_min_interval_seconds:
                    cached = self._last_sync_msa_result or {}
                    return {
                        'success': True,
                        'trigger': trigger,
                        'skipped': True,
                        'reason': 'recent_sync',
                        'cooldown_seconds': self.sync_min_interval_seconds,
                        'seconds_until_next_sync': max(0, int(self.sync_min_interval_seconds - elapsed_since_last)),
                        'parsehub_total_projects': cached.get('parsehub_total_projects', 0),
                        'parsehub_msa_projects': cached.get('parsehub_msa_projects', 0),
                        'sync_result': cached.get('sync_result', {}),
                    }

        use_local_lock = trigger in {'manual_api', 'manual'}
        lock_key = 'job:sync-msa'
        lock_owner = f'{trigger}:{datetime.utcnow().isoformat()}'
        local_lock_acquired = False
        if use_local_lock:
            local_lock_acquired = self._sync_msa_local_lock.acquire(blocking=False)
            if not local_lock_acquired:
                return {'success': True, 'skipped': True, 'reason': 'sync already running (local)'}
        else:
            if not self.db.acquire_automation_lock(lock_key, lock_owner, ttl_seconds=240):
                return {'success': True, 'skipped': True, 'reason': 'sync already running'}

        try:
            started = time.perf_counter()
            projects = fetch_all_projects(self.parsehub_api_key())
            fetched = time.perf_counter()
            msa_projects = [
                project for project in projects 
                if self.is_msa_title(project.get('title') or project.get('name'))
            ]
            filtered = time.perf_counter()
            sync_result = self.db.sync_projects(msa_projects)
            synced = time.perf_counter()
            result_payload = {
                'success': True,
                'trigger': trigger,
                'parsehub_total_projects': len(projects),
                'parsehub_msa_projects': len(msa_projects),
                'sync_result': sync_result,
                'timing_ms': {
                    'fetch_projects': int((fetched - started) * 1000),
                    'filter_msa': int((filtered - fetched) * 1000),
                    'sync_db': int((synced - filtered) * 1000),
                    'total': int((synced - started) * 1000),
                },
            }
            print(
                '[SYNC-MSA] timing_ms '
                f"fetch_projects={result_payload['timing_ms']['fetch_projects']} "
                f"filter_msa={result_payload['timing_ms']['filter_msa']} "
                f"sync_db={result_payload['timing_ms']['sync_db']} "
                f"total={result_payload['timing_ms']['total']}",
                flush=True,
            )
            with self._sync_msa_state_lock:
                self._last_sync_msa_completed_at_monotonic = time.monotonic()
                self._last_sync_msa_result = result_payload
            audit_payload = {
                'event_type': 'automation.sync_msa',
                'status': 'ok',
                'message': 'MSA sync completed',
                'details': {
                    'trigger': trigger,
                    'parsehub_total_projects': len(projects),
                    'parsehub_msa_projects': len(msa_projects),
                    'timing_ms': result_payload['timing_ms'],
                },
            }
            if trigger in {'manual_api', 'internal_api', 'manual'}:
                self._add_audit_event_async(**audit_payload)
            else:
                self.db.add_automation_audit_event(**audit_payload)
            return result_payload
        except Exception as exc:
            audit_payload = {
                'event_type': 'automation.sync_msa',
                'status': 'error',
                'message': 'MSA sync failed',
                'details': {'trigger': trigger, 'error': str(exc)},
            }
            if trigger in {'manual_api', 'internal_api', 'manual'}:
                self._add_audit_event_async(**audit_payload)
            else:
                self.db.add_automation_audit_event(**audit_payload)
            return {'success': False, 'error': str(exc)}
        finally:
            if use_local_lock:
                if local_lock_acquired:
                    self._sync_msa_local_lock.release()
            else:
                self.db.release_automation_lock(lock_key, lock_owner)

    def reconcile_active_runs(self, trigger: str = 'manual') -> dict[str, Any]:
        if not self.enabled:
            return {'success': False, 'error': 'Automation disabled'}

        lock_key = 'job:reconcile-active-runs'
        lock_owner = f'{trigger}:{datetime.utcnow().isoformat()}'
        if not self.db.acquire_automation_lock(lock_key, lock_owner, ttl_seconds=240):
            return {'success': True, 'skipped': True, 'reason': 'reconcile already running'}

        processed = 0
        succeeded = 0
        failed = 0
        try:
            active_runs = self.db.get_active_runs_for_reconciliation(limit=self.reconcile_limit)
            if not active_runs:
                return {'success': True, 'processed': 0, 'updated': 0, 'failed': 0}

            with ThreadPoolExecutor(max_workers=min(self.status_workers, self.max_workers)) as executor:
                futures = [executor.submit(self._reconcile_single_run, run, trigger) for run in active_runs]
                for future in as_completed(futures):
                    processed += 1
                    try:
                        result = future.result()
                        if result.get('success'):
                            succeeded += 1
                        else:
                            failed += 1
                    except Exception:
                        failed += 1

            self.db.add_automation_audit_event(
                event_type='automation.reconcile_active_runs',
                status='ok' if failed == 0 else 'partial',
                message='Active run reconciliation completed',
                details={
                    'trigger': trigger,
                    'processed': processed,
                    'updated': succeeded,
                    'failed': failed,
                },
            )
            return {'success': True, 'processed': processed, 'updated': succeeded, 'failed': failed}
        finally:
            self.db.release_automation_lock(lock_key, lock_owner)

    def reconcile_run_by_token(self, run_token: str, source: str = 'manual') -> dict[str, Any]:
        run_record = self.db.get_run_by_token(run_token)
        if not run_record:
            return {'success': False, 'error': f'Run {run_token} not found'}
        return self._reconcile_single_run(run_record, source)

    def _reconcile_single_run(self, run_record: dict[str, Any], source: str) -> dict[str, Any]:
        run_token = run_record.get('run_token')
        project_id = run_record.get('project_id')
        project_token = run_record.get('project_token')
        cumulative_id = run_record.get('project_run_cumulative_id')

        if not run_token or not project_id or not project_token:
            return {'success': False, 'error': 'Incomplete run record'}

        project_lock = f'project:{project_id}:automation'
        lock_owner = f'reconcile:{run_token}:{datetime.utcnow().isoformat()}'
        if not self.db.acquire_automation_lock(project_lock, lock_owner, ttl_seconds=120):
            return {'success': True, 'skipped': True, 'reason': 'project lock busy'}

        try:
            run_data = self.parsehub_get(f'/runs/{run_token}')
            pages_scraped = int(run_data.get('pages') or 0)
            data_ready = bool(run_data.get('data_ready'))
            status = str(run_data.get('status') or run_record.get('status') or 'unknown')

            self.db.upsert_run(
                project_id,
                run_token,
                status,
                pages_requested=run_record.get('pages_requested') or 1,
                pages_scraped=pages_scraped,
                data_ready=data_ready,
                start_time=run_data.get('start_time') or run_record.get('start_time'),
                end_time=run_data.get('end_time') or run_record.get('end_time'),
                project_run_cumulative_id=cumulative_id,
            )

            # Diagnostic log for every reconcile status check
            print(
                f'[RECONCILE] run={run_token} project={project_token} '
                f'status={status} data_ready={data_ready} pages_scraped={pages_scraped} '
                f'source={source}',
                flush=True,
            )

            normalized_status = status.strip().lower()
            is_terminal_success = normalized_status in {'complete', 'completed', 'success', 'succeeded'}
            if data_ready and is_terminal_success:
                print(
                    f'[RECONCILE] Run {run_token} is complete. Entering ingest+advance for project={project_token}.',
                    flush=True,
                )
                ingestion_result = self._ingest_and_advance(
                    project_id=project_id,
                    project_token=project_token,
                    run_token=run_token,
                    project_run_cumulative_id=cumulative_id,
                    source=source,
                )
                return {'success': ingestion_result.get('success', False), 'run_token': run_token, 'status': status}

            return {'success': True, 'run_token': run_token, 'status': status}
        except Exception as exc:
            self.db.add_automation_audit_event(
                event_type='automation.reconcile_run',
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                project_run_cumulative_id=cumulative_id,
                status='error',
                message='Failed to reconcile run',
                details={'error': str(exc), 'source': source},
            )
            return {'success': False, 'run_token': run_token, 'error': str(exc)}
        finally:
            self.db.release_automation_lock(project_lock, lock_owner)

    def _ingest_and_advance(
        self,
        project_id: int,
        project_token: str,
        run_token: str,
        project_run_cumulative_id: str | None,
        source: str,
    ) -> dict[str, Any]:
        ingestion = self.db.get_run_ingestion_status(run_token)
        if ingestion and ingestion.get('status') == 'success':
            return {'success': True, 'run_token': run_token, 'skipped': True, 'reason': 'already ingested'}

        run_lock_key = f'run-ingest:{run_token}'
        lock_owner = f'ingest:{datetime.utcnow().isoformat()}'
        if not self.db.acquire_automation_lock(run_lock_key, lock_owner, ttl_seconds=180):
            return {'success': True, 'run_token': run_token, 'skipped': True, 'reason': 'ingest lock busy'}

        try:
            self.db.mark_run_ingestion(run_token, project_id, status='processing')
            ingestor = ParseHubDataIngestor()
            ingest_result = ingestor.ingest_run(
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                project_run_cumulative_id=project_run_cumulative_id,
            )

            if not ingest_result.get('success'):
                print(
                    f"[RECONCILE] ❌ Ingestion failed for run {run_token}: "
                    f"{ingest_result.get('error') or ingest_result.get('message') or 'unknown error'}",
                    flush=True,
                )
                self.db.mark_run_ingestion(
                    run_token,
                    project_id,
                    status='failed',
                    inserted_count=0,
                    last_error=str(ingest_result.get('error') or ingest_result.get('message') or 'ingestion failed'),
                )
                self.db.add_automation_audit_event(
                    event_type='automation.ingest_run',
                    project_id=project_id,
                    project_token=project_token,
                    run_token=run_token,
                    project_run_cumulative_id=project_run_cumulative_id,
                    status='error',
                    message='Run ingestion failed',
                    details={'source': source, 'ingest_result': ingest_result},
                )
                return {'success': False, 'error': ingest_result.get('error') or ingest_result.get('message')}

            self.db.mark_run_ingestion(
                run_token,
                project_id,
                status='success',
                inserted_count=int(ingest_result.get('inserted', 0) or 0),
            )
            if not self.db.automation_audit_event_exists('automation.ingest_run', run_token=run_token, status='ok'):
                self.db.add_automation_audit_event(
                    event_type='automation.ingest_run',
                    project_id=project_id,
                    project_token=project_token,
                    run_token=run_token,
                    project_run_cumulative_id=project_run_cumulative_id,
                    status='ok',
                    message='Run ingestion completed',
                    details={'source': source, 'inserted': int(ingest_result.get('inserted', 0) or 0)},
                )

            # Keep metadata progress cumulative across resumed runs. ParseHub run pages are often
            # relative to the run itself (e.g., 1..N each run), so rely on the resume checkpoint
            # to derive absolute page progression for the current project session.
            metadata = self.db.get_metadata_by_project_token(project_token)
            run_record = self.db.get_run_by_token(run_token)
            auto_resume_state = self.db.get_auto_resume_state(project_id)
            run_pages_scraped = int((run_record or {}).get('pages_scraped') or 0)
            checkpoint_page = auto_resume_state.get('auto_resume_max_page_checkpoint')
            checkpoint_page_num = int(checkpoint_page) if checkpoint_page is not None else None
            if metadata:
                existing_progress = int(metadata.get('current_page_scraped') or 0)
                total_pages_cap = int(metadata.get('total_pages') or 0)
                if checkpoint_page_num is not None and run_pages_scraped > 0:
                    cumulative_progress = checkpoint_page_num + run_pages_scraped
                else:
                    cumulative_progress = run_pages_scraped
                if total_pages_cap > 0:
                    cumulative_progress = min(cumulative_progress, total_pages_cap)
                if cumulative_progress > existing_progress:
                    self.db.update_metadata_progress(
                        str(metadata.get('personal_project_id')),
                        current_page_scraped=cumulative_progress,
                    )

            return self._evaluate_and_advance_resume(project_id, project_token, source=source)
        finally:
            self.db.release_automation_lock(run_lock_key, lock_owner)

    def _evaluate_and_advance_resume(self, project_id: int, project_token: str, source: str) -> dict[str, Any]:
        # If a run for this project is already in flight, defer evaluation. This prevents a race
        # where one reconcile thread has just kicked off a resume run (and persisted a fresh
        # checkpoint) while another thread enters here, sees the new checkpoint == max_page,
        # and incorrectly persists `auto_resume_blocked = TRUE`.
        recent_runs = self.db.get_runs_by_project(project_id, limit=5)
        if any(str(r.get('status') or '').strip().lower() in {'initialized', 'running', 'queued'} for r in recent_runs):
            return {'success': True, 'skipped': True, 'reason': 'active_run_in_flight'}

        resume_state = self.db.prepare_resume_status(project_token)
        active_session = self.db.get_latest_active_cumulative_session(project_id)
        active_cumulative_id = active_session.get('project_run_cumulative_id') if active_session else None

        if not resume_state.get('success'):
            self.db.add_automation_audit_event(
                event_type='automation.resume_evaluate',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='error',
                message='Resume evaluation failed',
                details={'source': source, 'resume_state': resume_state},
            )
            return {'success': False, 'error': resume_state.get('error') or 'Resume evaluation failed'}

        if resume_state.get('inconsistent'):
            self.db.add_automation_audit_event(
                event_type='automation.resume_evaluate',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='blocked',
                message='Inconsistent data detected; automation halted for project',
                details={'source': source, 'resume_state': resume_state},
            )
            return {'success': True, 'blocked': True, 'reason': 'inconsistent_data'}

        if resume_state.get('project_complete'):
            closed = self.db.close_latest_active_cumulative_session(project_id)
            self.db.add_automation_audit_event(
                event_type='automation.session_close',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=closed.get('project_run_cumulative_id'),
                status='ok',
                message='Project complete; cumulative session closed',
                details={'source': source, 'resume_state': resume_state, 'closed': closed.get('closed')},
            )
            return {'success': True, 'project_complete': True, 'closed': closed.get('closed', False)}

        if not resume_state.get('resumable'):
            return {'success': True, 'resumable': False, 'reason': 'not_ready'}

        # ─── SAFETY GATE ────────────────────────────────────────────────────────
        # Automatic resume starts a real ParseHub run without any user action.
        # This is gated by AUTOMATION_RESUME_ENABLED (default: 0 = OFF).
        # When disabled, we log the decision so it is visible in the audit trail
        # and the operator can set AUTOMATION_RESUME_ENABLED=1 to re-enable.
        # ────────────────────────────────────────────────────────────────────────
        now_utc = datetime.utcnow().isoformat()
        resume_diagnostics = {
            'source': source,
            'evaluated_at_utc': now_utc,
            'project_token': project_token,
            'project_id': project_id,
            'max_page_scraped': resume_state.get('max_page_scraped'),
            'total_pages': resume_state.get('total_pages'),
            'next_page_number': resume_state.get('next_page_number'),
            'generated_next_page_url': resume_state.get('generated_next_page_url'),
            'active_project_run_cumulative_id': resume_state.get('active_project_run_cumulative_id'),
            'resume_enabled': self.resume_enabled,
        }

        if not self.resume_enabled:
            # Log that a resume WOULD have fired but is blocked by the safety gate.
            print(
                f'[AUTOMATION] AUTO-RESUME BLOCKED (AUTOMATION_RESUME_ENABLED=0): '
                f'project={project_token} max_page={resume_state.get("max_page_scraped")} '
                f'total_pages={resume_state.get("total_pages")} source={source}',
                flush=True,
            )
            self.db.add_automation_audit_event(
                event_type='automation.resume_blocked',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='blocked',
                message=(
                    'Auto-resume is disabled (AUTOMATION_RESUME_ENABLED=0). '
                    'Set AUTOMATION_RESUME_ENABLED=1 in backend/.env to enable paginated auto-continuation.'
                ),
                details=resume_diagnostics,
            )
            return {'success': True, 'skipped': True, 'reason': 'auto_resume_disabled'}

        # Auto-resume is explicitly enabled — run additional safeguards before firing.

        total_pages = int(resume_state.get('total_pages') or 0)
        max_page_scraped = int(resume_state.get('max_page_scraped') or 0)
        next_page_number = resume_state.get('next_page_number')

        # ── Safeguard A: total_pages must be > 1 ─────────────────────────────
        if total_pages <= 1:
            _diag = {**resume_diagnostics, 'block_reason': 'total_pages_lte_1', 'total_pages': total_pages}
            print(
                f'[AUTOMATION] AUTO-RESUME BLOCKED (total_pages<=1): '
                f'project={project_token} total_pages={total_pages} source={source}',
                flush=True,
            )
            self.db.add_automation_audit_event(
                event_type='automation.resume_blocked',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='blocked',
                message=(
                    f'Auto-resume blocked: total_pages={total_pages} (must be >1). '
                    'Single-page projects run once and do not auto-continue.'
                ),
                details=_diag,
            )
            return {'success': True, 'skipped': True, 'reason': 'total_pages_lte_1'}

        # ── Safeguard B: next_page_number must be valid ───────────────────────
        if not next_page_number or int(next_page_number) < 2:
            _diag = {**resume_diagnostics, 'block_reason': 'invalid_next_page', 'next_page_number': next_page_number}
            print(
                f'[AUTOMATION] AUTO-RESUME BLOCKED (no valid next page): '
                f'project={project_token} next_page_number={next_page_number} source={source}',
                flush=True,
            )
            self.db.add_automation_audit_event(
                event_type='automation.resume_blocked',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='blocked',
                message=f'Auto-resume blocked: next_page_number={next_page_number} is missing or invalid.',
                details=_diag,
            )
            return {'success': True, 'skipped': True, 'reason': 'invalid_next_page'}

        # ── Safeguard C: persistent auto_resume_blocked DB flag ───────────────
        ar_state = self.db.get_auto_resume_state(project_id)
        if ar_state.get('auto_resume_blocked'):
            checkpoint = ar_state.get('auto_resume_max_page_checkpoint')
            # Self-heal stale persistent blocks once forward progress is observed again.
            if checkpoint is not None and max_page_scraped > int(checkpoint):
                self.db.clear_auto_resume_blocked(project_id)
                self.db.add_automation_audit_event(
                    event_type='automation.resume_unblocked',
                    project_id=project_id,
                    project_token=project_token,
                    project_run_cumulative_id=active_cumulative_id,
                    status='ok',
                    message='Auto-resume block cleared automatically after forward progress recovered',
                    details={
                        **resume_diagnostics,
                        'previous_checkpoint': int(checkpoint),
                        'observed_max_page': max_page_scraped,
                        'reason': 'forward_progress_recovered',
                    },
                )
                print(
                    f'[AUTOMATION] AUTO-RESUME UNBLOCKED: '
                    f'project={project_token} checkpoint={checkpoint} max_page={max_page_scraped} source={source}',
                    flush=True,
                )
                ar_state = self.db.get_auto_resume_state(project_id)
            else:
                _diag = {
                    **resume_diagnostics,
                    'block_reason': 'auto_resume_blocked_flag',
                    'auto_resume_max_page_checkpoint': checkpoint,
                }
                print(
                    f'[AUTOMATION] AUTO-RESUME BLOCKED (persistent DB flag): '
                    f'project={project_token} checkpoint={checkpoint} '
                    f'max_page={max_page_scraped} source={source}',
                    flush=True,
                )
                self.db.add_automation_audit_event(
                    event_type='automation.resume_blocked',
                    project_id=project_id,
                    project_token=project_token,
                    project_run_cumulative_id=active_cumulative_id,
                    status='blocked',
                    message=(
                        'Auto-resume blocked: auto_resume_blocked=1 is set in the DB from a prior '
                        'no-progress cycle. Clear it with: '
                        'UPDATE projects SET auto_resume_blocked=0 WHERE id=<id>.'
                    ),
                    details=_diag,
                )
                return {'success': True, 'skipped': True, 'reason': 'auto_resume_blocked_flag'}

        # ── Safeguard D: forward-progress check ──────────────────────────────
        # Compare current max_page against the checkpoint saved before the last resume.
        # If no improvement, block permanently (persisted in DB).
        checkpoint_page = ar_state.get('auto_resume_max_page_checkpoint')
        if checkpoint_page is not None and max_page_scraped <= checkpoint_page:
            _diag = {
                **resume_diagnostics,
                'block_reason': 'no_forward_progress',
                'prev_max_page': checkpoint_page,
                'latest_max_page': max_page_scraped,
                'total_pages': total_pages,
            }
            print(
                f'[AUTOMATION] AUTO-RESUME BLOCKED AND PERSISTED (no forward progress): '
                f'project={project_token} prev_max_page={checkpoint_page} '
                f'latest_max_page={max_page_scraped} total_pages={total_pages} source={source}',
                flush=True,
            )
            self.db.set_auto_resume_blocked(project_id)
            self.db.add_automation_audit_event(
                event_type='automation.resume_blocked',
                project_id=project_id,
                project_token=project_token,
                project_run_cumulative_id=active_cumulative_id,
                status='blocked',
                message=(
                    f'Auto-resume blocked and persisted: max_page_scraped ({max_page_scraped}) '
                    f'did not advance past checkpoint ({checkpoint_page}). '
                    'auto_resume_blocked=1 written to DB to prevent looping.'
                ),
                details=_diag,
            )
            return {
                'success': True,
                'skipped': True,
                'reason': 'no_forward_progress',
                'prev_max_page': checkpoint_page,
                'latest_max_page': max_page_scraped,
            }

        # ── All safeguards passed — allow auto-resume ─────────────────────────
        print(
            f'[AUTOMATION] AUTO-RESUME STARTING: '
            f'project={project_token} next_page={next_page_number} '
            f'of {total_pages} total source={source}',
            flush=True,
        )
        self.db.add_automation_audit_event(
            event_type='automation.resume_allowed',
            project_id=project_id,
            project_token=project_token,
            project_run_cumulative_id=active_cumulative_id,
            status='ok',
            message='Auto-resume is enabled and all safeguards passed; starting next page run',
            details={
                **resume_diagnostics,
                'prev_max_page': checkpoint_page,
                'total_pages': total_pages,
                'next_page_number': next_page_number,
            },
        )
        return self._start_automated_resume(project_id, project_token, resume_state, source=source)

    def _start_automated_resume(
        self,
        project_id: int,
        project_token: str,
        resume_state: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        active_runs = self.db.get_runs_by_project(project_id, limit=10)
        if any((r.get('status') in {'initialized', 'running', 'queued'}) for r in active_runs):
            return {'success': True, 'skipped': True, 'reason': 'active run exists'}

        total_pages = int(resume_state.get('total_pages') or 0)
        max_page_scraped = int(resume_state.get('max_page_scraped') or 0)
        generated_url = resume_state.get('generated_next_page_url')
        pages_remaining = max(1, total_pages - max_page_scraped)

        run_payload: dict[str, Any] = {'pages': pages_remaining}
        if generated_url:
            run_payload['start_url'] = generated_url

        run_info = self.parsehub_post(f'/projects/{project_token}/run', run_payload)
        run_token = run_info.get('run_token')
        if not run_token:
            return {'success': False, 'error': 'ParseHub did not return run token for automated resume'}

        # Diagnostic: log every automated run trigger with full context
        print(
            f'[RUN-TRIGGER] source=auto_resume token={project_token} run_token={run_token} '
            f'next_page={resume_state.get("next_page_number")} '
            f'of {resume_state.get("total_pages")} pages_remaining={pages_remaining} '
            f'start_url={generated_url}',
            flush=True,
        )

        cumulative_id = resume_state.get('active_project_run_cumulative_id')
        if not cumulative_id:
            # Safety fallback: attach to currently active cumulative session.
            cumulative_id = self.db.attach_run_to_cumulative_session(
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                force_new_session=False,
            )
        else:
            self.db.attach_run_to_cumulative_session(
                project_id=project_id,
                project_token=project_token,
                run_token=run_token,
                force_new_session=False,
            )

        self.db.upsert_run(
            project_id,
            run_token,
            run_info.get('status', 'running'),
            pages_requested=pages_remaining,
            pages_scraped=0,
            data_ready=False,
            start_time=run_info.get('start_time'),
            project_run_cumulative_id=cumulative_id,
        )

        # Snapshot the max_page baseline AFTER the new run is registered. Persisting the
        # checkpoint earlier created a race window where a concurrent reconcile thread could
        # observe `max_page_scraped == checkpoint` (with no active run yet visible) and
        # incorrectly mark the project as no-forward-progress.
        self.db.set_auto_resume_checkpoint(project_id, max_page_scraped)

        metadata = self.db.get_metadata_by_project_token(project_token)
        personal_project_id = str(metadata.get('personal_project_id')) if metadata else None
        if personal_project_id:
            self.db.update_metadata_progress(
                personal_project_id,
                current_page_scraped=max_page_scraped,
                next_page_url=generated_url,
                last_run_data=run_info.get('start_time'),
                update_date=run_info.get('start_time') or None,
            )

        self.db.add_automation_audit_event(
            event_type='automation.start_resume',
            project_id=project_id,
            project_token=project_token,
            run_token=run_token,
            project_run_cumulative_id=cumulative_id,
            status='ok',
            message='Automated resume started',
            details={
                'source': source,
                'pages_remaining': pages_remaining,
                'start_url': generated_url,
                'next_page_number': resume_state.get('next_page_number'),
                'max_page_checkpoint': max_page_scraped,
            },
        )
        return {'success': True, 'run_token': run_token, 'project_run_cumulative_id': cumulative_id}
