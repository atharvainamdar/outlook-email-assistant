FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps only (cached layer) — do NOT install the app package
COPY pyproject.toml .
RUN pip install --no-cache-dir $(python3 -c "
import tomllib, pathlib
d = tomllib.loads(pathlib.Path('pyproject.toml').read_text())
print(' '.join(d['project']['dependencies']))
")

# Copy app source (always fresh — never cached by pip)
COPY app/ app/

# Create data directory
RUN mkdir -p /data

ENV EA_DATA_DIR=/data
ENV EA_HOST=0.0.0.0
ENV EA_PORT=8000

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
