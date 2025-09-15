# user_management/Dockerfile
#FROM python:3.11-slim
#
#WORKDIR /app
#
#ENV PYTHONDONTWRITEBYTECODE=1
#ENV PYTHONUNBUFFERED=1
#
#RUN apt-get update && apt-get install -y \
#    build-essential \
#    libpq-dev \
#    && rm -rf /var/lib/apt/lists/*
#
#COPY requirements.txt .
#RUN pip install --no-cache-dir -r requirements.txt
#
#COPY .. .
#
#EXPOSE 8000
#
#CMD ["gunicorn", "tara_user_management.wsgi:application", "--bind", "0.0.0.0:8000"]
# Use slim base for smaller image
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (better cache)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy only the app source code (not the whole repo root)
COPY . .

# Expose Django/Gunicorn port
EXPOSE 8000

# Run gunicorn
CMD ["gunicorn", "Tara.wsgi:application", "--bind", "0.0.0.0:8000"]
