# AI Software Incident Investigator

A privacy-focused, self-hosted system that collects telemetry, correlates incident evidence, and uses a local LLM to investigate possible root causes.

## Project Structure

```text
├── api-contract.md          # Formal REST API conventions and schemas
├── archeteture.md           # High-level architecture specification
├── backend/                 # FastAPI backend, evidence processor, and AI agent
└── frontend/                # Next.js dashboard, incident timeline, and reports
```

## Quick Start

### Backend Setup
```bash
cd backend
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

## Documentation
- [System Architecture](archeteture.md)
- [API Contracts](api-contract.md)
