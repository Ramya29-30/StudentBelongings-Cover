# Multi-stage build: Node builds the React UI once; the runtime image contains only Python + the built UI.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build            # vite writes ../frontend/dist  ->  /frontend/dist

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_ENV=production
WORKDIR /app
COPY backend/requirements.lock.txt backend/requirements.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.lock.txt
COPY backend/ backend/
COPY --from=ui /frontend/dist frontend/dist
RUN useradd --system --create-home app && mkdir -p /app/backend/data && chown -R app /app/backend/data
USER app
WORKDIR /app/backend
EXPOSE 8000
VOLUME ["/app/backend/data"]
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status==200 else 1)"
# Production refuses to start without SECRET_KEY, COOKIE_SECURE=true and SEED_DEMO_DATA=false (see docs/DEPLOYMENT.md).
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
