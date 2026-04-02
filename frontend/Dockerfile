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
    && chown -R appuser:appuser /var/cache/nginx /var/run /usr/share/nginx/html \
    && chmod -R 755 /var/cache/nginx /var/run

USER appuser

EXPOSE 5173

CMD ["nginx", "-g", "daemon off;"]
