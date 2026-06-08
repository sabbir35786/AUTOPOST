FROM python:3.11-slim-bookworm

ENV PIP_ROOT_USER_ACTION=ignore

# Install system dependencies for PyGObject, PyCairo, PangoCairo, and libraqm
# See: backend/app/routers/persona_image_templates.py (Pango/Cairo rendering)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    pkg-config \
    libcairo2 \
    libcairo2-dev \
    libgirepository1.0-dev \
    gobject-introspection \
    python3-gi \
    python3-gi-cairo \
    libgirepository-1.0-1 \
    libpango-1.0-0 \
    gir1.2-pango-1.0 \
    fontconfig \
    fonts-noto \
    fonts-noto-core \
    fonts-noto-extra \
    libharfbuzz-dev \
    libraqm0 \
    libraqm-dev \
    python3-dev \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Install Python bindings for Pango/Cairo (PyGObject, pycairo)
RUN pip install --no-cache-dir PyGObject pycairo

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
