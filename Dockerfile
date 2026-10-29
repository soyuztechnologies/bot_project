# =============================================================
# Dockerfile — SEO Automation Bot
# =============================================================
# Multi-purpose image used by both services in docker-compose:
#   dashboard  -> python dashboard/app.py   (Flask, port 5050)
#   bot        -> python launcher.py        (automation runner)
#
# Chrome runs in headless mode inside the container (no display
# needed). The host mounts config.json, data/ and logs/ so that
# settings saved in the dashboard persist across restarts.
# =============================================================

# -----------------------------
# Base Image
# -----------------------------
FROM python:3.12-slim

# -----------------------------
# Environment Variables
# -----------------------------
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# -----------------------------
# System Dependencies
# (Chrome requires these libs)
# -----------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    unzip \
    gnupg \
    ca-certificates \
    xvfb \
    xdg-utils \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libu2f-udev \
    libvulkan1 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    && rm -rf /var/lib/apt/lists/*

# -----------------------------
# Google Chrome (stable)
# -----------------------------
RUN wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# -----------------------------
# Working Directory
# -----------------------------
WORKDIR /app

# -----------------------------
# Python Dependencies
# (installed before COPY . . so
#  this layer is cached on code
#  changes — only re-runs when
#  requirements.txt changes)
# -----------------------------
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    seleniumbase install chromedriver && \
    seleniumbase install uc_driver

# -----------------------------
# Copy Project Files
# -----------------------------
COPY . .

# -----------------------------
# Default Command
# (overridden per service in
#  docker-compose.yml)
# -----------------------------
ENTRYPOINT ["python"]
CMD ["launcher.py"]
