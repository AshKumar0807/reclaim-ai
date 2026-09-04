# FILE: backend/Dockerfile
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
# Install core + optional prod drivers (psycopg, pika) for the production profile.
RUN pip install --no-cache-dir -r requirements.txt "psycopg[binary]>=3.1" "pika>=1.3"
COPY . .
EXPOSE 8000
CMD ["sh","-c","uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
