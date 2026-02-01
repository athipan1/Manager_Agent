# Stage 1: Base
# This image is intended to be a shared base for all Python services.
# It installs the common dependencies from requirements.base.txt.
FROM public.ecr.aws/docker/library/python:3.12-slim as base

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
COPY requirements.prod.base.txt .
RUN pip install --no-cache-dir -r requirements.prod.base.txt

# Create a non-root user for security.
RUN addgroup --system app && adduser --system --group app

# Grant ownership of venv to the app user.
RUN chown -R app:app /opt/venv

USER app


# Stage 2: Builder
# This stage installs the service-specific production dependencies into a venv.
FROM base as builder

# Copy and install the service-specific production dependencies.
# The base image already contains the base dependencies.
COPY requirements.prod.txt ./
RUN pip install --no-cache-dir -r requirements.prod.txt


# Stage 3: Runner
# This is the final, lean production image.
# It starts from our shared base image, which contains the common venv.
FROM base as runner

# Copy the venv with the service-specific dependencies from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy the application code and the healthcheck script.
COPY ./app /app/app
COPY ./healthcheck.py /app/healthcheck.py

# Ensure the app user owns the copied files.
USER root
RUN chown -R app:app /app
USER app

# Expose the application port.
EXPOSE 8000

# Use the lightweight Python-based healthcheck.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["python", "/app/healthcheck.py"]

# Set the command to run the application.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
