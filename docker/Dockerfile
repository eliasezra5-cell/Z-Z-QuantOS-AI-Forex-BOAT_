FROM python:3.11-slim AS backend
WORKDIR /app
COPY backend-py/requirements.txt ./backend-py/
RUN pip install --no-cache-dir -r backend-py/requirements.txt
COPY backend-py/ ./backend-py/
EXPOSE 3001
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3001"]

FROM node:22-alpine AS frontend-build
WORKDIR /app
# Frontend is an npm workspace of the root package; use the root lockfile so
# `npm ci` is reproducible (frontend/ has no lockfile of its own).
COPY package*.json ./
COPY frontend/package*.json ./frontend/
RUN npm ci --workspace=frontend
COPY frontend/ ./frontend/
RUN npm run build -w frontend

FROM backend AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends nginx \
 && rm -rf /var/lib/apt/lists/*
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
COPY docker/nginx-prod.conf /etc/nginx/conf.d/default.conf
EXPOSE 80 3001
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
