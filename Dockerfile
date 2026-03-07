FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies just in case for cryptography/grpcio
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files (respecting .dockerignore)
COPY . .

# Cloud Run injects the PORT environment variable. We use uvicorn to bind to it.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
