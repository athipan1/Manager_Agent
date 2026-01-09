# Stage 1: Builder
# This stage installs all Python dependencies into a virtual environment.
FROM python:3.12-slim as builder

# Set working directory
WORKDIR /app

# Prevent Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE 1
# Ensure Python output is sent straight to the terminal without buffering.
ENV PYTHONUNBUFFERED 1

# Create a virtual environment
RUN python -m venv /opt/venv

# Activate virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install dependencies
# This is done in a separate step to leverage Docker's layer caching.
# The dependencies will only be re-installed if requirements.txt changes.
COPY requirements.txt .
COPY requirements.base.txt
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runner
# This stage creates the final, lean production image.
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Create a non-root user for security
RUN addgroup --system app && adduser --system --group app

# Install curl for the healthcheck
USER root
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy the virtual environment with dependencies from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy the application code
COPY ./app /app/app

# Activate the virtual environment for the final image
ENV PATH="/opt/venv/bin:$PATH"

# Switch to the non-root user
USER app

# Expose the port the app runs on
EXPOSE 80

# Healthcheck to ensure the service is running correctly
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD curl -f http://localhost:80/health || exit 1

# Command to run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
