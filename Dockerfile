FROM node:22-alpine AS mindmap_frontend

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends libcairo2 tesseract-ocr tesseract-ocr-eng poppler-utils antiword && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY LICENSE ./
COPY dashboard ./dashboard
COPY profiles ./profiles
COPY static ./static
COPY templates ./templates
COPY --from=mindmap_frontend /static/mindmaps ./static/mindmaps

LABEL org.opencontainers.image.title="WidgetDeck" \
      org.opencontainers.image.source="https://github.com/Gink3/WidgetDeck"

EXPOSE 8000
CMD ["gunicorn", "--workers", "2", "--timeout", "300", "--bind", "0.0.0.0:8000", "app:app"]
