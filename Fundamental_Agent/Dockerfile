# Stage 1: Builder
# This stage installs all dependencies into a virtual environment.
FROM python:3.12-slim AS builder

# Prevent Python from writing pyc files.
ENV PYTHONDONTWRITEBYTECODE 1

# Keep the environment clean.
ENV PYTHONUNBUFFERED 1

# Create and activate a virtual environment.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set a working directory.
WORKDIR /app

# Install dependencies from the lock file.
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt


# Stage 2: Final Image
# This stage creates the final, minimal image for production.
FROM python:3.12-slim

# Set the working directory.
WORKDIR /app

# Create a non-root user to run the application.
RUN addgroup --system appuser && adduser --system --ingroup appuser appuser

# Copy the virtual environment from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Copy the application code.
COPY ./app ./app

# Set ownership of the files to the non-root user.
RUN chown -R appuser:appuser /app /opt/venv

# Switch to the non-root user.
USER appuser

# Make the virtual environment's Python the default.
ENV PATH="/opt/venv/bin:$PATH"

# Expose the port the app runs on.
EXPOSE 8001

# Run the application.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
