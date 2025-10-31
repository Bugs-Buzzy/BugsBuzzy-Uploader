# --- Build stage ---
FROM python:3.11-slim AS build

WORKDIR /app

COPY requirements.txt ./

# Install build dependencies and wheel, then install Python deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 

WORKDIR /app

# Install curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged user
RUN adduser --disabled-password --no-create-home --gecos '' appuser

# Copy Python packages from build stage (installed system-wide)
COPY --from=build /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=build /usr/local/bin /usr/local/bin

COPY main.py ./
COPY gunicorn_config.py ./
COPY requirements.txt ./

# Include static dir
COPY public ./public

# Create uploads directory (will be volume-mounted in production)
RUN mkdir -p uploads

# Chown for security (skip if volume mounted for production)
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 9000

CMD ["gunicorn", "main:app", "-c", "gunicorn_config.py"]
