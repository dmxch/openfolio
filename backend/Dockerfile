# Stage 1: Dependencies
FROM python:3.12-slim AS deps

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.12-slim

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . .

RUN adduser --disabled-password --no-create-home --gecos "" appuser \
    && mkdir -p /app/data/imports \
    && chown -R appuser:appuser /app/data
USER appuser

ENV PYTHONPATH=/app
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --retries=3 --start-period=120s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

ENTRYPOINT ["bash", "entrypoint.sh"]
# --forwarded-allow-ips "*": Backend-Port ist nur auf 127.0.0.1 bzw. im
# Docker-Netz exponiert, einziger Pfad ist der nginx-Proxy — dessen
# X-Forwarded-For darf vertraut werden (Container-IPs sind dynamisch,
# daher kein festes Subnetz). Ohne das Flag sähen request.client.host
# und damit alle Rate-Limit-Keys nur die nginx-IP (Review 2026-06-10, H6).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "uvloop", "--forwarded-allow-ips", "*"]
