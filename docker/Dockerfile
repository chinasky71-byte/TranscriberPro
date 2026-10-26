# syntax=docker/dockerfile:1.7
#
# One image per backend (ADR-004). Build from the repository root:
#
#   docker build --build-arg BACKEND=rocm -t transcriberpro:rocm -f docker/Dockerfile .
#   docker build --build-arg BACKEND=cuda -t transcriberpro:cuda -f docker/Dockerfile .
#   docker build --build-arg BACKEND=cpu  -t transcriberpro:cpu  -f docker/Dockerfile .
#
# The image ships no GPU drivers and no model weights: both come from the host
# (driver) and from the volumes `/models`, `/data`, `/media`.
ARG BACKEND=rocm

FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Runtime tools the pipeline shells out to. No driver, no kernel package: the
# container uses the host driver through the container runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ffmpeg \
      mkvtoolnix \
      tesseract-ocr \
      tesseract-ocr-ita \
      tesseract-ocr-eng \
      libgomp1 \
      libsndfile1 \
      ca-certificates \
      curl \
 && rm -rf /var/lib/apt/lists/*

FROM base AS builder
ARG BACKEND
# Toolchain needed only when a wheel has to be built (CPU image: llama-cpp-python).
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential cmake git \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements.txt requirements-rocm.txt requirements-web.txt ./
RUN python -m venv /opt/venv \
 && . /opt/venv/bin/activate \
 && pip install --upgrade pip \
 && case "$BACKEND" in \
      rocm) pip install -r requirements-rocm.txt ;; \
      cuda) pip install -r requirements.txt ;; \
      cpu)  grep -Ev '^(torch|torchaudio)==|abetlen\.github\.io' requirements.txt > /tmp/requirements-cpu.txt \
            && pip install -r /tmp/requirements-cpu.txt \
            && pip install --index-url https://download.pytorch.org/whl/cpu \
                 torch==2.8.0 torchaudio==2.8.0 ;; \
      *) echo "BACKEND must be rocm, cuda or cpu (got '$BACKEND')" >&2; exit 2 ;; \
    esac \
 && pip install -r requirements-web.txt

FROM base AS runtime
ARG BACKEND
LABEL org.opencontainers.image.title="Transcriber Pro" \
      org.opencontainers.image.description="Headless transcription, translation and subtitle pipeline with WebUI (${BACKEND})" \
      org.opencontainers.image.source="https://github.com/chinasky71-byte/TranscriberPro"

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    TP_DATA_DIR=/data \
    TP_MODELS_DIR=/models \
    HOME=/home/tp

WORKDIR /app
# Only code: models, media, config and logs are volumes (ADR-004).
COPY core ./core
COPY utils ./utils
COPY web ./web
COPY glossary_engine ./glossary_engine
COPY bench ./bench
COPY main.py ./

RUN useradd --create-home --uid 1000 tp \
 && mkdir -p /data /models /media \
 && chown -R tp:tp /data /models /media

USER tp
EXPOSE 8080
VOLUME ["/data", "/models"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

# Non-loopback bind: TP_WEB_TOKEN is mandatory and `web.main` refuses to start
# without it, so a container without a token fails fast instead of exposing an
# open API.
CMD ["python", "-m", "web.main", "--host", "0.0.0.0", "--port", "8080"]
