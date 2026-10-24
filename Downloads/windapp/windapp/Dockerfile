# syntax=docker/dockerfile:1
# ---- stage 1: build the React UI
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- stage 2: FastAPI serving the API and the built UI on one origin
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOST=0.0.0.0 PORT=8000 STATIC_DIR=/srv/static
WORKDIR /srv
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=ui /ui/dist ./static
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health',timeout=4)"
CMD ["sh", "-c", "uvicorn app.main:app --host ${HOST} --port ${PORT}"]
