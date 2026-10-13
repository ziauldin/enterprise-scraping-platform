# ParseHub v2 - Setup and Run Guide

This project has:
- `backend/` - Flask API (Snowflake as primary database)
- `frontend/` - Next.js web app

## Prerequisites

- Python 3.12+ (recommended)
- Node.js 18+ and npm
- (Optional) Docker + Docker Compose

## 1) Environment Setup

### Backend env

Create backend env file:

```bash
cp backend/.env.example backend/.env
```

Use `backend/.env.example` as the source of truth and add every listed variable to `backend/.env` with proper values (replace all placeholder values).

Then set at least:
- `PARSEHUB_API_KEY`
- `BACKEND_API_KEY`
- `AUTOMATION_ENABLED=1`
- `AUTOMATION_SCHEDULER_ENABLED=1`
- `AUTOMATION_RECONCILE_SECONDS=60` (or lower for faster progression)
- `AUTOMATION_RESUME_ENABLED=1` (required for unattended multi-page continuation)

Database:
- Fill all `SNOWFLAKE_*` variables in `backend/.env`
- On first run, the backend can auto-create the warehouse, database, and schema named there (`SNOWFLAKE_AUTO_PROVISION=true`). Your Snowflake user needs `CREATE WAREHOUSE`, `CREATE DATABASE`, and `CREATE SCHEMA` (e.g. `ACCOUNTADMIN` on a trial). If your org restricts that, create those objects in the Snowflake UI and set `SNOWFLAKE_AUTO_PROVISION=false`.

### Frontend env

Create frontend env file:

```bash
cp frontend/.env.example frontend/.env.local
```

Use `frontend/.env.example` as the source of truth and add every listed variable to `frontend/.env.local` with proper values.

Ensure:
- `BACKEND_API_KEY` matches `backend/.env`
- `NEXT_PUBLIC_BACKEND_URL=http://localhost:5000` (for local dev)

## 2) Backend Setup and Start

From project root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
python api_server.py
```

Backend will start on `http://localhost:5000` (unless changed in env).

## 3) Frontend Setup and Start

Open a second terminal, from project root:

```bash
cd frontend
npm install
npm run dev
```

Frontend will start on `http://localhost:3000`.

## 4) Start Both with One Command (Optional)

From project root:

```bash
python start.py --backend
```

This starts backend and frontend together for local development.

## 5) Run with Docker (Optional)

From project root:

```bash
docker compose up --build
```

Services:
- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5000`

Make sure these files exist before running compose:
- `backend/.env`
- `frontend/.env.local`

## 6) Resume Automation (Recommended)

Resume progression should be handled by the backend automation worker, not by keeping project pages open in the browser.

When `AUTOMATION_RESUME_ENABLED=1`, the backend reconcile loop:
- detects completed runs,
- ingests run data,
- evaluates resume state (`max_page_scraped`, `total_pages`, `next_page_number`),
- and starts the next ParseHub run automatically when safe.

This enables users to start multiple projects and leave the UI while pagination continues in the background.

Recommended flags in `backend/.env`:
- `AUTOMATION_ENABLED=1`
- `AUTOMATION_SCHEDULER_ENABLED=1`
- `AUTOMATION_RECONCILE_SECONDS=60` (or 30 for faster handoff)
- `AUTOMATION_RESUME_ENABLED=1`

Notes:
- Keep the frontend Resume button as a manual fallback.
- If auto-resume appears blocked, check automation audit events and any persisted `auto_resume_blocked` state for the project.

## Common Issues

- **401 Unauthorized**: `BACKEND_API_KEY` mismatch between backend and frontend env files.
- **Frontend cannot reach backend**: verify `NEXT_PUBLIC_BACKEND_URL` and backend is running on port `5000`.
- **Snowflake connection errors**: verify all `SNOWFLAKE_*` values.
