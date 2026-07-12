# =============================================================================
# DownloadKit Docker Image
# Based on python:3.11-slim (matches NAS Debian 12 Python 3.11) 
# =============================================================================
FROM python:3.11-slim

LABEL maintainer="downloadkit" \
      description="Multi-platform resource downloader (Douyin, Bilibili, YouTube, Xiaohongshu, Music)"

# ── System dependencies ──────────────────────────────────────────────────────
# ffmpeg:   required by bilibili (audio+video merge) and motion photo (Google Motion Photo)
# nodejs:   required by execjs (douyin JS signature)
#            NAS host has ffmpeg 7.1.3 installed, but container stays self-contained
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        ca-certificates \
        tzdata \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# ── Timezone ─────────────────────────────────────────────────────────────────
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── Locale ───────────────────────────────────────────────────────────────────
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONIOENCODING=utf-8

# ── Application setup ────────────────────────────────────────────────────────
WORKDIR /app

# Copy dependency manifest first (better layer caching)
COPY pyproject.toml README.md ./
COPY downloadkit/ ./downloadkit/

# Install project with media support (Pillow + moviepy for motion photo)
# Skip playwright (too heavy, ~500MB; only needed as fallback for some douyin parsing)
RUN pip install --no-cache-dir -e ".[media,douyin]"

# Copy remaining files
COPY server.py run.py ./
COPY tests/ ./tests/

# ── Runtime config ───────────────────────────────────────────────────────────
EXPOSE 8765

# Create volume mount points
RUN mkdir -p /root/.downloadkit /app/downloads

# Volume mount points (config/cookies/history.db, downloads)
VOLUME ["/root/.downloadkit", "/app/downloads"]

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765')" || exit 1

# Start server (run as root — single-user NAS deployment, matches existing containers pattern)
CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8765", "--log-level", "info"]
