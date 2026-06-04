FROM python:3.11-slim-bookworm

# Install system dependencies for PyGObject, PyCairo, and PangoCairo
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libcairo2-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    gir1.2-pango-1.0 \
    fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 10000

# Start command using Render's PORT env variable (default to 10000)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}
