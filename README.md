# 🕸️ Enterprise Scraping & Analytics Platform

A full stack platform that automates large-scale data extraction across multiple projects, with a Next.js dashboard, a Flask backend, and Snowflake for storage and analytics.

![Next.js](https://img.shields.io/badge/Next.js-000000?style=flat-square&logo=nextdotjs&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white)
![Python](https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white)
![Snowflake](https://img.shields.io/badge/Snowflake-29B5E8?style=flat-square&logo=snowflake&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=flat-square&logo=celery&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white)
![ParseHub](https://img.shields.io/badge/ParseHub-1F2937?style=flat-square&logoColor=white)

## Features

- Dashboard to manage scraping projects and runs
- Large-scale extraction across many projects at once
- **Metadata-driven resume system:** every run stores checkpoints, so an interrupted job restarts from where it stopped instead of from the beginning
- Dynamic pagination handling for sites with changing page structures
- Extracted data stored in Snowflake for analytics

## Architecture

```mermaid
flowchart LR
    UI[Next.js dashboard] --> API[Flask API]
    API --> S[Scraping jobs / ParseHub]
    S --> M[(Run metadata + checkpoints)]
    M -->|resume on failure| S
    S --> DW[(Snowflake)]
```

## Run locally

```bash
git clone https://github.com/ziauldin/enterprise-scraping-platform.git
cd enterprise-scraping-platform
cp backend/.env.example backend/.env     # add your ParseHub and Snowflake credentials
cp frontend/.env.example frontend/.env
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
python start.py --backend                # starts the Flask API and the Next.js app
```

Or run everything with Docker: `docker compose up --build`. See [docs/SETUP.md](docs/SETUP.md) for the full environment reference, resume automation, and common issues. Kubernetes manifests are in [infrastructure/](infrastructure/).

## Tech stack

Next.js, React, TypeScript, Flask, Python, Celery, Redis, ParseHub API, Snowflake, Docker, Kubernetes

**Timeline:** early 2026 to April 2026
