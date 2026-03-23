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

ENTRYPOINT ["bash", "entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--loop", "uvloop"]
