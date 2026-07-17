FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directories
RUN mkdir -p /app/data/exports /app/data/errors

# Entrypoint (auto-init DB on first run)
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

# Environment defaults
ENV APP_DATA_DIR=/app/data
ENV APP_HOST=0.0.0.0
ENV APP_PORT={{api_port}}

EXPOSE {{api_port}}

CMD ["./entrypoint.sh"]
