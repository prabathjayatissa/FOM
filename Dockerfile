# FOM Mapper - Release 0.1 Prototype container image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.7.1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install ".[dev]"

# Application code
COPY app ./app
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

# Create non-root user
RUN useradd --create-home --shell /bin/bash fom && \
    chown -R fom:fom /app
USER fom

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
