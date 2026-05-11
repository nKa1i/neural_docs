FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY requirements.txt .
RUN apt-get update && apt-get install -y fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY app/ ./app/
COPY tests/ ./tests/
COPY main.py .

# LM Studio runs on the host — override via env var at runtime:
#   docker run -e LM_STUDIO_HOST=host.docker.internal -e LM_STUDIO_MODEL=qwen/qwen2.5-v1-7b ...
ENV LM_STUDIO_HOST=host.docker.internal
ENV LM_STUDIO_MODEL=qwen/qwen2.5-v1-7b

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
