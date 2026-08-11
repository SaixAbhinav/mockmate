# Backend image, serving BOTH the Render web service (ADR 0025) and, via the
# AWS Lambda Web Adapter extension below, AWS Lambda behind API Gateway
# (ADR 0029). Python only - the SPA is built/served separately (a Render
# static site for Render, the frontend's own path for Lambda), rewriting
# /api/* to whichever of these is running.
FROM python:3.11-slim

# AWS Lambda Web Adapter (https://github.com/aws/aws-lambda-web-adapter),
# pinned to the latest tagged release as of this writing (v1.0.1 - see the
# project's GitHub Releases for newer tags). Copying its binary into
# /opt/extensions/ is how Lambda auto-discovers it as an "internal"
# extension; it translates API Gateway's Lambda events into plain HTTP
# requests against the app's own port, so the FastAPI app needs no
# Lambda-specific code. This file is inert outside a Lambda execution
# environment, so it does not change Render/local behavior at all.
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.0.1 /lambda-adapter /opt/extensions/lambda-adapter

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
#
# On Lambda, `infra/lambda.tf` sets PORT=8080 and AWS_LWA_PORT=8080 so uvicorn
# and the Web Adapter agree on where the app listens - no CMD change needed
# there either; the adapter proxies API Gateway traffic to this same port.
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
