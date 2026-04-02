# Stage 1: Build
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .
RUN npm run build

# Stage 2: Serve
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Non-root user (CIS Docker Benchmark)
RUN adduser -D -H -s /sbin/nologin appuser \
    && chown -R appuser:appuser /var/cache/nginx /usr/share/nginx/html \
    && sed -i 's|/run/nginx.pid|/tmp/nginx.pid|' /etc/nginx/nginx.conf \
    && sed -i '/^user /d' /etc/nginx/nginx.conf

USER appuser

EXPOSE 5173

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=30s \
    CMD wget -q -O /dev/null http://localhost:5173/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
