FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (cached layer)
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy app source AFTER install so code changes always take effect
# The pip install above puts deps in site-packages; we override the
# app/ package with the latest source below.
COPY app/ app/

# Create data directory
RUN mkdir -p /data

ENV EA_DATA_DIR=/data
ENV EA_HOST=0.0.0.0
ENV EA_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
