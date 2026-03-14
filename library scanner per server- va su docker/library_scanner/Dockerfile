FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia SOLO il package Python
COPY library_scanner/ ./library_scanner/

# Crea directory dati persistenti
RUN mkdir -p /app/data/logs /app/data/db

# Utente non-root
RUN useradd -m -u 1000 scanner && \
    chown -R scanner:scanner /app
USER scanner

EXPOSE 6680

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:6680/health')" || exit 1

CMD ["python", "-m", "uvicorn", "library_scanner.api.main:app", "--host", "0.0.0.0", "--port", "6680"]
