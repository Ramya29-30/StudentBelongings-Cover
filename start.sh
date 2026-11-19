#!/usr/bin/env bash
# StudentBelongings Cover - Linux/macOS launcher (backend + pre-built React UI). Node.js is NOT needed to run this.
set -e
cd "$(dirname "$0")"
[ -f frontend/dist/index.html ] || { echo "frontend/dist missing: run ./build-frontend.sh first (needs Node.js 20+)"; exit 1; }
cd backend
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install --quiet -r requirements.lock.txt
echo "Open http://localhost:8000"
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
