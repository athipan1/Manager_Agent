# 1. Base image
FROM python:3.11-slim

# 2. Set working directory
WORKDIR /app

# 3. Copy & Install dependencies
COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy app source code
COPY ./app /app/app

# 5. Expose port
EXPOSE 80

# 6. Run FastAPI
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "80"]
