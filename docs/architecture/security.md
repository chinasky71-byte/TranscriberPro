# Security

The product is a single-user local service. The threat model is accordingly
small, but explicit.

## Assumptions

- One trusted user, one machine.
- Media files are on local or mounted storage.
- The service is reachable from `localhost` by default; LAN access is opt-in.
- No multi-tenant isolation is provided.

## Web exposure (target)

| Control | Rule |
|---|---|
| Bind address | `127.0.0.1` by default; `--host` explicit and logged |
| Auth | optional bearer token via `TP_WEB_TOKEN`; required when binding to a non-loopback address |
| CSRF | required for state-changing requests when a cookie session is used |
| Transport | plain HTTP on loopback; TLS terminated by a reverse proxy on LAN |
| Headers | `X-Content-Type-Options: nosniff`, `Content-Security-Policy` for the UI |

## File access

- The API accepts paths only under configured roots (`allowed_media_roots`);
  resolve with `realpath` and reject anything outside them.
- Reject traversal and symlink escapes.
- Output and log directories are separate from media roots.
- No file upload in v1; containers mount media at a known path.
- Serving OCR review images only from the current job's temp directory.

## Secrets

- Never in the repository (hard rule in `AGENTS.md`).
- Never in logs, events, error messages or API responses.
- The config API returns only `is_set` flags and accepts write-only updates.
- Tokens may come from the environment (`TP_WEB_TOKEN`,
  `HUGGINGFACE_TOKEN`) or the config file.

## Containers

- Run as a non-root user; map the host UID/GID for writable volumes.
- No driver or kernel files in images.
- Models and media mounted read-only where possible.
- Root filesystem read-only when feasible; explicit writable volumes for
  `TP_DATA_DIR`, `TP_MODELS_DIR` and the output directory.
- Pin image tags to a version; do not deploy `latest`.

## Dependencies and supply chain

- Pin versions in the requirements files.
- Scan images and dependencies in CI.
- Do not fetch arbitrary models by URL at runtime; use Hugging Face IDs or
  verified local paths.

## What the project never does

- Install or modify GPU drivers, DKMS modules or kernel parameters.
- Request root at runtime.
- Phone home or upload media anywhere except the explicitly configured
  OpenSubtitles upload.
