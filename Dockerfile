FROM python:3.11-slim

# Install system dependencies (ffmpeg, opencv requirements)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files
COPY . .

# Install python packages
RUN pip install --no-cache-dir hatchling && pip install --no-cache-dir -e .

ENV PORT=3000

CMD ["sh", "-c", "uvicorn src.server:app --host 0.0.0.0 --port ${PORT}"]
