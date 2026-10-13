import os
from datetime import datetime
from typing import Any

import requests

try:
    from backend.celery_app import celery_app
    from backend.database import get_database
except ImportError:
    from celery_app import celery_app
    from database import get_database


def _backend_headers() -> dict[str, str]:
    api_key = os.getenv('BACKEND_API_KEY', '').strip()
    return {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }


def _backend_base_url() -> str:
    return os.getenv('BACKEND_INTERNAL_URL', os.getenv('NEXT_PUBLIC_BACKEND_URL', 'http://localhost:5001')).rstrip('/')


@celery_app.task(name='backend.celery_tasks.process_due_schedules')
def process_due_schedules() -> dict[str, Any]:
    """Claim due schedules and trigger ParseHub runs via existing run endpoint."""
    db = get_database()
    now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    claim_limit = max(1, int(os.getenv('SCHEDULED_RUN_CLAIM_LIMIT', '25')))
    stale_trigger_seconds = max(30, int(os.getenv('SCHEDULED_RUN_STALE_TRIGGER_SECONDS', '180')))
    stale_trigger_cutoff_utc = datetime.utcfromtimestamp(
        datetime.utcnow().timestamp() - stale_trigger_seconds
    ).strftime('%Y-%m-%dT%H:%M:%SZ')
    claimed = db.claim_due_scheduled_runs(
        now_utc_iso=now_utc,
        limit=claim_limit,
        stale_triggered_before_iso=stale_trigger_cutoff_utc,
    )

    # Diagnostic: log every trigger invocation whether or not rows were claimed
    print(
        f'[SCHEDULER] process_due_schedules invoked: now_utc={now_utc} '
        f'stale_cutoff={stale_trigger_cutoff_utc} claimed={len(claimed)} rows',
        flush=True,
    )
    for row in claimed:
        print(
            f'[SCHEDULER] CLAIMED schedule_id={row.get("id")} '
            f'project={row.get("project_token")} '
            f'schedule_type={row.get("schedule_type")} '
            f'scheduled_time_utc={row.get("scheduled_run_time_utc")} '
            f'status_before={row.get("status")} retry_count={row.get("retry_count", 0)} '
            f'max_retries={row.get("max_retries", 0)} '
            f'is_active={row.get("is_active")} '
            f'timezone={row.get("timezone")}',
            flush=True,
        )

    processed = 0
    success = 0
    failed = 0
    backend_url = _backend_base_url()

    for schedule in claimed:
        schedule_id = int(schedule['id'])
        project_id = int(schedule['project_id'])
        project_token = str(schedule['project_token'])

        # Defense-in-depth: verify this schedule is still in 'triggered' state
        # before dispatching.  A concurrent call or a status refresh could have
        # already marked it completed or failed between the claim SELECT and now.
        current = db.get_scheduled_run_by_id(schedule_id)
        if not current or current.get('status') not in ('triggered',):
            continue
        schedule_type = str(current.get('schedule_type') or 'one_time').strip().lower()

        processed += 1

        # Diagnostic: log every scheduled dispatch attempt with full row context
        print(
            f'[SCHEDULER-DISPATCH] source=scheduled_heartbeat '
            f'schedule_id={schedule_id} project={project_token} '
            f'schedule_type={schedule_type} '
            f'scheduled_time_utc={current.get("scheduled_run_time_utc")} '
            f'now_utc={now_utc} retry_count={current.get("retry_count", 0)} '
            f'is_active={current.get("is_active")}',
            flush=True,
        )

        try:
            response = requests.post(
                f'{backend_url}/api/projects/{project_token}/run',
                json={},
                headers=_backend_headers(),
                timeout=30,
            )
            payload = response.json()
            if response.ok and payload.get('success'):
                if schedule_type == 'recurring':
                    # For recurring schedules, consume this occurrence exactly once
                    # and immediately advance next_run_utc for future eligibility.
                    db.mark_recurring_run_triggered(schedule_id=schedule_id, run_token=payload.get('run_token'))
                else:
                    db.mark_scheduled_run_in_progress(schedule_id=schedule_id, run_token=payload.get('run_token'))
                db.add_automation_audit_event(
                    event_type='scheduler.run_triggered',
                    project_id=project_id,
                    project_token=project_token,
                    run_token=payload.get('run_token'),
                    status='ok',
                    message='Scheduled run triggered',
                    details={
                        'schedule_id': schedule_id,
                        'scheduled_run_time_utc': schedule.get('scheduled_run_time_utc'),
                        'retry_count': schedule.get('retry_count', 0),
                    },
                )
                success += 1
            else:
                error_message = payload.get('error', f'HTTP {response.status_code}')
                if schedule_type == 'recurring':
                    # Avoid duplicate re-dispatch of the same occurrence.
                    # If current occurrence could not be started, skip it and
                    # move to the next valid recurrence.
                    db.mark_recurring_run_skipped(schedule_id=schedule_id, error_message=error_message)
                else:
                    # 409 means the project is already running — do not retry
                    # automatically; the user must reschedule once the active run
                    # finishes. Other failures (5xx, timeouts) still respect
                    # the configured max_retries budget.
                    no_retry_statuses = {409, 404}
                    force_fail = response.status_code in no_retry_statuses
                    db.mark_scheduled_run_failed(
                        schedule_id=schedule_id,
                        error_message=error_message,
                        force_fail=force_fail,
                    )
                db.add_automation_audit_event(
                    event_type='scheduler.run_trigger_failed',
                    project_id=project_id,
                    project_token=project_token,
                    status='error',
                    message='Scheduled run failed to trigger',
                    details={
                        'schedule_id': schedule_id,
                        'scheduled_run_time_utc': schedule.get('scheduled_run_time_utc'),
                        'retry_count': schedule.get('retry_count', 0),
                        'error': error_message,
                    },
                )
                failed += 1
        except Exception as exc:
            if schedule_type == 'recurring':
                db.mark_recurring_run_skipped(schedule_id=schedule_id, error_message=str(exc))
            else:
                db.mark_scheduled_run_failed(schedule_id=schedule_id, error_message=str(exc))
            db.add_automation_audit_event(
                event_type='scheduler.run_trigger_exception',
                project_id=project_id,
                project_token=project_token,
                status='error',
                message='Scheduled run trigger raised exception',
                details={
                    'schedule_id': schedule_id,
                    'scheduled_run_time_utc': schedule.get('scheduled_run_time_utc'),
                    'retry_count': schedule.get('retry_count', 0),
                    'error': str(exc),
                },
            )
            failed += 1

    return {
        'success': True,
        'processed': processed,
        'triggered': success,
        'failed': failed,
        'stale_trigger_cutoff_utc': stale_trigger_cutoff_utc,
        'checked_at_utc': now_utc,
    }
