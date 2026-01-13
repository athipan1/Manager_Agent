# --- Base Image ---
# This image is intended to be a shared base for all Python services.
# It installs the common dependencies from requirements.base.txt.
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files and buffer output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create and activate a virtual environment.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install base dependencies into the venv.
# This layer will be cached and reused by other services.
COPY requirements.base.txt .
RUN pip install --no-cache-dir -r requirements.base.txt

# Create a non-root user for security.
RUN addgroup --system app && adduser --system --group app
USER app
