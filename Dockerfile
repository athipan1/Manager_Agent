# Stage 1: Builder
# This stage installs the service-specific production dependencies into a venv.
FROM painaidee-base:latest as builder

# Set working directory.
WORKDIR /app

# Prevent Python from writing pyc files or buffering output.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy and install the service-specific production dependencies.
# The base image already contains the base dependencies.
COPY requirements.prod.txt ./
RUN pip install --no-cache-dir -r requirements.prod.txt


# Stage 2: Runner
# This is the final, lean production image.
# It starts from our shared base image, which contains the common venv.
FROM painaidee-base:latest

# Set working directory.
WORKDIR /app

# Copy the venv with the service-specific dependencies from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy the application code and the healthcheck script.
COPY ./app /app/app
COPY ./healthcheck.py /app/healthcheck.py

# Ensure the app user owns the copied files.
USER root
RUN chown -R app:app /app
USER app

# Set the PATH to include the virtual environment's binaries.
ENV PATH="/opt/venv/bin:$PATH"

# Expose the application port.
EXPOSE 80

# Use the lightweight Python-based healthcheck.
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD ["python", "/app/healthcheck.py"]

# Set the command to run the application.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
