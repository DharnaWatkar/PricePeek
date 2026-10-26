# ---------- Stage 1: build the React (Vite) frontend ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY Frontend/package-lock.json Frontend/package.json ./
RUN npm ci
COPY Frontend/ ./
RUN npm run build

# ---------- Stage 2: FastAPI + headful Chromium under Xvfb ----------
# The scrapers launch a real headed browser to pass bot-checks; on a Linux
# server that requires a virtual display (xvfb). Real Google Chrome is
# installed because it passes bot-checks much better than the bundled build.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb ca-certificates gnupg wget \
 && wget -qO- https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --batch --dearmor | tee /usr/share/keyrings/google-chrome.gpg > /dev/null \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb stable main" \
      > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY Backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY Backend/ ./
COPY --from=web /web/dist /app/web

ENV WEB_DIST=/app/web \
    PYTHONUNBUFFERED=1

EXPOSE 8000
# --host 0.0.0.0 + Render's PORT; xvfb gives the headful browsers a display
CMD ["sh", "-c", "xvfb-run -a uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
