# syntax=docker/dockerfile:1

# --- Build stage ---
FROM python:3.11-slim AS build

WORKDIR /app

COPY requirements.txt ./

# Install build dependencies and wheel, then install Python deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential gcc \
    && pip install --upgrade pip wheel \
    && pip install --user --no-cache-dir -r requirements.txt

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 

WORKDIR /app

# Create unprivileged user
RUN adduser --disabled-password --no-create-home --gecos '' appuser

# Copy only site-packages from build, not full Python env
COPY --from=build /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

COPY main.py ./
COPY gunicorn_config.py ./
COPY requirements.txt ./
# Include static and upload dirs if they exist
COPY public ./public
COPY uploads ./uploads

# Chown for security (skip if volume mounted for production)
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 1000

CMD ["gunicorn", "main:app", "-c", "gunicorn_config.py"]
