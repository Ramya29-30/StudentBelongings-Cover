#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/frontend-react"
npm ci
npm run build
echo "Built: $(cd .. && pwd)/frontend/dist"
