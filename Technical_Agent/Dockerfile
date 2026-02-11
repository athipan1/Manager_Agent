# Stage 1: Builder
FROM python:3.9-slim AS builder
WORKDIR /app

# Install git and build tools
RUN apt-get update && apt-get install -y git build-essential --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Install a compatible version of numpy first
RUN pip install --no-cache-dir "numpy<1.23"

# Copy requirements and build wheels
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2: Runtime
FROM python:3.9-slim
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install git
RUN apt-get update && apt-get install -y git --no-install-recommends && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appgroup && useradd --no-log-init -r -g appgroup appuser

# Copy wheels and requirements
COPY --from=builder /wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt

# Copy source code
COPY ./app /app
RUN chown -R appuser:appgroup /app
USER appuser

# Environment and port
ENV PORT=8002
EXPOSE $PORT

# Run Gunicorn with Uvicorn workers
CMD ["gunicorn", "--bind", "0.0.0.0:8002", "--workers", "2", "--worker-class", "uvicorn.workers.UvicornWorker", "main:app"]
