FROM node:22-alpine AS frontend
WORKDIR /app
COPY package*.json vite.config.js ./
COPY frontend ./frontend
RUN npm install && npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app
COPY requirements.txt ./
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb pulseaudio ffmpeg gstreamer1.0-tools gstreamer1.0-x gstreamer1.0-pulseaudio \
    gstreamer1.0-plugins-base gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav && \
    pip install --no-cache-dir -r requirements.txt && \
    python -m playwright install --with-deps chromium && \
    rm -rf /var/lib/apt/lists/*
COPY backend ./backend
COPY --from=frontend /app/public ./public
EXPOSE 8000
CMD ["sh", "-c", "pulseaudio --system --daemonize --disallow-exit --exit-idle-time=-1 || true; python main.py"]
