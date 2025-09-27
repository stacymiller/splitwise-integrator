# Use official lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing .pyc files and enable unbuffered logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System dependencies required by python-magic and image/HEIF handling
# - libmagic1: runtime for python-magic
# - libheif1: runtime for pillow-heif (HEIC/HEIF)
# - ca-certificates: HTTPS requests (OpenAI, Telegram, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       libmagic1 \
       libheif1 \
       ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install Python dependencies first (better caching)
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# Copy project
COPY . .

# Create uploads directory (also declared as a volume for persistence)
RUN mkdir -p uploads
VOLUME ["/app/uploads"]

# Expose Flask port used by web/app.py (app.py binds to 0.0.0.0:5001)
EXPOSE 5001

# Default environment variables can be overridden at runtime
# ENV WEB_APP_URL="http://localhost:5001"

# Start the combined web app and (optionally) the Telegram bot
# The bot will start only if TELEGRAM_BOT_TOKEN is provided
CMD ["python", "app.py"]
