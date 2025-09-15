# -------------------
# 1. Base builder image
# -------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Prevent Python from writing pyc files / forcing stdout flush
#Prevent Python from writing pyc files / forcing stdout flush
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into /install (not system-wide)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip && \
    pip install --prefix=/install -r requirements.txt

# -------------------
# 2. Final runtime image
# -------------------
FROM python:3.11-slim

WORKDIR /app

# Copy installed dependencies from builder stage
COPY --from=builder /install /usr/local

# Create log file and give permissions
RUN touch /app/application.log && chmod 666 /app/application.log

# Add a non-root user (security best practice)
RUN addgroup --system appgroup && adduser --system appuser --ingroup appgroup
USER appuser

# Copy project files
COPY . .

# Expose Django/Gunicorn port
EXPOSE 8000

# Healthcheck endpoint (Django’s default or custom /healthz)
#HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
#    CMD curl -f http://localhost:8000/user_management/test/ || exit 1

# Run Gunicorn
CMD ["gunicorn", "Tara.wsgi:application", "--bind", "0.0.0.0:8000"]
