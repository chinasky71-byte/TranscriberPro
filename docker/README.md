# Docker (ADR-004)

One image per backend, one compose file. The image contains the application
and the system tools it shells out to (ffmpeg, mkvtoolnix, tesseract); it never
contains GPU drivers or model weights.

| Backend | Image | Host requirement |
|---|---|---|
| `rocm` | torch/torchaudio `+rocm7.0` | `amdgpu` driver, `/dev/kfd`, `/dev/dri`, user in `video` and `render` |
| `cuda` | torch/torchaudio `+cu126` | NVIDIA driver + NVIDIA container toolkit |
| `cpu` | torch/torchaudio CPU wheels | none (smoke tests, slow production) |

## Build

From the repository root:

```bash
docker build --build-arg BACKEND=rocm -t transcriberpro:rocm -f docker/Dockerfile .
docker build --build-arg BACKEND=cuda -t transcriberpro:cuda -f docker/Dockerfile .
docker build --build-arg BACKEND=cpu  -t transcriberpro:cpu  -f docker/Dockerfile .
```

## Run

```bash
export TP_WEB_TOKEN="$(openssl rand -base64 24)"
export TP_MEDIA_DIR=/srv/media          # mounted read-write: the SRT lands next to the video
export TP_MODELS_DIR_HOST=$PWD/models   # model cache on the host

docker compose -f docker/compose.yaml --profile rocm up --build
```

Then open `http://<host>:8080` and sign in with the token.

Compose variables:

| Variable | Default | Meaning |
|---|---|---|
| `TP_WEB_TOKEN` | **required** | bearer token and login password |
| `TP_MEDIA_DIR` | `../samples` | media root mounted at `/media` (read-write) |
| `TP_MODELS_DIR_HOST` | `../models` | model cache mounted at `/models` |
| `TP_PORT` | `8080` | published port |
| `TP_TAG` | `latest` | image tag used by compose |

## Volumes and users

- `tp-data` (named volume) holds `config.json`, `jobs.json`, queue logs and OCR
  review sessions. It is the container `/data`.
- `/models` and `/media` are bind mounts. Media must be writable because the
  pipeline writes `<video>.<lang>.srt` next to the file.
- The container runs as uid 1000 (`tp`). If your host user has another uid, set
  `user:` in compose or `chown` the volumes; do not run the container as root.

## What is not in the image

- GPU drivers, kernel modules, ROCm/CUDA system libraries: they come from the
  host.
- Model weights: mount the cache. Models are downloaded at runtime into
  `/models` by the first job that needs them.
- The Qt desktop GUI: it is optional and not installed (`requirements-gui.txt`
  is not copied into the image).

## Notes

- `ipc: host` and `seccomp:unconfined` are the usual AMD compute workarounds;
  they do not add privileges over the GPU device itself.
- A container without `TP_WEB_TOKEN` refuses to start (the server binds
  `0.0.0.0`).
- HTTP on a LAN exposes the token: put a TLS reverse proxy or a VPN in front.
- The image build downloads several GB on `rocm`/`cuda`. CI builds the three
  images without running a GPU job; the GPU smoke test runs on a self-hosted
  runner.
