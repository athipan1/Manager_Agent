# Stage 1: Builder - Install dependencies
FROM python:3.12-slim as builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR="/tmp/numba_cache"

# Create and activate a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy and install requirements
COPY requirements.lock.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.lock.txt

# Stage 2: Dev - For running tests
FROM builder as dev

ENV APP_HOME=/home/app/web
WORKDIR $APP_HOME

# Copy the application and test code
COPY ./learning_agent ./learning_agent
COPY ./tests ./tests

CMD ["pytest"]

# Stage 3: Final - Create the production image
FROM python:3.12-slim

# Create a non-root user and group
RUN addgroup --system app && adduser --system --group app

# Set environment variables
ENV HOME=/home/app \
    APP_HOME=/home/app/web \
    NUMBA_CACHE_DIR="/tmp/numba_cache"

RUN mkdir -p $APP_HOME
WORKDIR $APP_HOME

# Copy the virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy the application code
COPY ./learning_agent ./learning_agent

# Set the path to use the virtual environment's executables
ENV PATH="/opt/venv/bin:$PATH"

# Change ownership of the app directory
RUN chown -R app:app $APP_HOME

# Switch to the non-root user
USER app

EXPOSE 8004

CMD ["uvicorn", "learning_agent.main:app", "--host", "0.0.0.0", "--port", "8004"]
