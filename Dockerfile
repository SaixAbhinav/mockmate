# Backend image for the Render web service (ADR 0025). Python only - the SPA is
# built and served by a separate Render static site, which rewrites /api/* here.
FROM python:3.11-slim

# Faster, quieter installs; no .pyc clutter in the layer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so a code-only change reuses this layer.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app

# The Runner executes untrusted Candidate code (ADR 0025 accepts the residual
# risk); run as an unprivileged user so it cannot write the app directory.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Render supplies $PORT, so a shell is needed to expand it - but `exec` replaces
# that shell with uvicorn, leaving uvicorn as PID 1. Without it uvicorn would be
# a child of sh and would never see Render's SIGTERM on redeploy, turning every
# deploy into a hard kill after the grace period.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
