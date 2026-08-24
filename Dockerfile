# =========================================================
# SEO & YouTube Automation Bot
# =========================================================

FROM python:3.12-slim

# =========================================================
# Environment
# =========================================================

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DISPLAY=:99

# =========================================================
# Working Directory
# =========================================================

WORKDIR /app

# =========================================================
# System Dependencies
# =========================================================

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    unzip \
    gnupg \
    ca-certificates \
    xvfb \
    xauth \
    xdg-utils \
    fonts-liberation \
    fonts-dejavu \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
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
    libxshmfence1 \
    libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# =========================================================
# Google Chrome
# =========================================================

RUN wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
    | gpg --dearmor -o /usr/share/keyrings/google.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
    > /etc/apt/sources.list.d/google.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# =========================================================
# Microsoft Edge
# =========================================================

RUN curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
    | gpg --dearmor -o /usr/share/keyrings/microsoft-edge.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-edge.gpg] https://packages.microsoft.com/repos/edge stable main" \
    > /etc/apt/sources.list.d/microsoft-edge.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    microsoft-edge-stable && \
    rm -rf /var/lib/apt/lists/*

# =========================================================
# Firefox
# =========================================================

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    firefox-esr && \
    rm -rf /var/lib/apt/lists/*

# =========================================================
# Brave
# =========================================================

RUN curl -fsSLo \
    /usr/share/keyrings/brave-browser-archive-keyring.gpg \
    https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg && \
    curl -fsSLo \
    /etc/apt/sources.list.d/brave-browser-release.sources \
    https://brave-browser-apt-release.s3.brave.com/brave-browser.sources && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    brave-browser && \
    rm -rf /var/lib/apt/lists/*

# =========================================================
# Opera
# =========================================================

RUN wget -qO- https://deb.opera.com/archive.key \
    | gpg --dearmor -o /usr/share/keyrings/opera.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/opera.gpg] https://deb.opera.com/opera-stable/ stable non-free" \
    > /etc/apt/sources.list.d/opera.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    opera-stable && \
    rm -rf /var/lib/apt/lists/*

# =========================================================
# Python Dependencies
# =========================================================

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# =========================================================
# SeleniumBase Drivers
# =========================================================

RUN seleniumbase get uc_driver && \
    seleniumbase get chromedriver 135 && \
    seleniumbase get edgedriver && \
    seleniumbase get geckodriver 
    
# =========================================================
# Copy Project
# =========================================================

COPY . .

# =========================================================
# Runtime Directories
# =========================================================

RUN mkdir -p /app/profiles /app/logs

# =========================================================
# Start
# =========================================================

ENTRYPOINT ["python"]
CMD ["launcher.py"]