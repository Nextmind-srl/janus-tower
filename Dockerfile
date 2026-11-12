# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="JanusTower — Cloud AI FinOps & Security Control Tower" \
      org.opencontainers.image.description="Read-only FinOps, Shadow AI telemetry & security posture control tower for Google Cloud AI" \
      org.opencontainers.image.licenses="MIT"

# PORT must match the published port (-p 8095:8095): the OAuth redirect URI is built from it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8095 \
    AUTO_OPEN_BROWSER=0

WORKDIR /app

# Create non-root execution user
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin appuser

# Runtime dependency (urllib3)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source files
COPY server.py ./
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY index.html ./
# Theme CSS is part of the frontend assembly (server.py rebuilds index.html from these at startup)
COPY Design/tokens.css Design/components.css Design/jt-theme.css ./Design/
# Logos are inlined in index.html; the folder is also served by the /Design/logos/ fallback route
COPY Design/logos/ ./Design/logos/

# Pre-create runtime data directory with non-root ownership
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

USER appuser

EXPOSE 8095

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, http.client; c = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('PORT', 8095)), timeout=3); c.request('GET', '/api/auth/status'); r = c.getresponse(); exit(0 if r.status == 200 else 1)"

CMD ["python", "server.py"]
