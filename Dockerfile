# Stage 1: Builder
# This stage installs all Python dependencies into a virtual environment.
FROM python:3.12-slim as builder

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE=1
# Ensure Python output is sent straight to the terminal without buffering.
ENV PYTHONUNBUFFERED=1

# Create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# ---- Dependencies Layer (cached) ----
COPY requirements.txt .
COPY requirements.base.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runner
FROM python:3.12-slim

WORKDIR /app

# Create non-root user
RUN addgroup --system app && adduser --system --group app

USER root
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY ./app /app/app

ENV PATH="/opt/venv/bin:$PATH"

USER app

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD curl -f http://localhost:80/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]