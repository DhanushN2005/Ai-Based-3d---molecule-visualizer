FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as a non-root user; the app writes outputs/, molecules/ and data/ at runtime.
RUN useradd --create-home app && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'))"

# One worker on purpose: rate limits and caches live in memory.
# Set TRUST_PROXY=1 (docker run -e TRUST_PROXY=1) when running behind a reverse proxy.
CMD ["sh", "-c", "gunicorn main:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:${PORT}"]
