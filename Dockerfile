# 1. Base image
FROM python:3.11-slim

# 2. Set working directory
WORKDIR /app

# 3. Install system dependencies (git จำเป็นมาก)
RUN apt-get update \
    && apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

# 4. Clone repositories (ครั้งเดียวตอน build)
RUN git clone https://github.com/athipan1/Technical_Agent.git
RUN git clone https://github.com/athipan1/Fundamental_Agent.git

# 5. Install Python dependencies
# (ถ้าแต่ละ repo มี requirements.txt)
RUN pip install --no-cache-dir \
    -r Technical_Agent/requirements.txt \
    -r Fundamental_Agent/requirements.txt

# 6. Copy orchestrator / app code (repo นี้)
COPY ./app /app/app
COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r requirements.txt

# 7. Expose port
EXPOSE 80

# 8. Run FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]