FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps only (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bust cache for app source on every build
ARG BUILD_TS=0
RUN echo "build: ${BUILD_TS}"

# Copy app source (always fresh — never cached by pip)
COPY app/ app/

# Create data directory
RUN mkdir -p /data

ENV EA_DATA_DIR=/data
ENV EA_HOST=0.0.0.0
ENV EA_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
