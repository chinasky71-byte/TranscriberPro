"""WebUI entry point.

    python -m web.main [--host 0.0.0.0] [--port 8080]

Authentication: set `TP_WEB_TOKEN` (or pass `--token`). A non-loopback host
refuses to start without a token.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from web.auth import is_loopback, token_from_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcriber Pro WebUI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data-dir", default=os.environ.get("TP_DATA_DIR", ""))
    parser.add_argument("--models-dir", default=os.environ.get("TP_MODELS_DIR", ""))
    parser.add_argument("--token", default=None, help="override TP_WEB_TOKEN")
    args = parser.parse_args(argv)

    token = (args.token or token_from_env() or "").strip() or None
    if not is_loopback(args.host) and not token:
        print("Refusing to bind a non-loopback address without a token.", file=sys.stderr)
        print("Set TP_WEB_TOKEN or pass --token. Generate one with:", file=sys.stderr)
        print("  python -c \"import secrets; print(secrets.token_urlsafe(32))\"", file=sys.stderr)
        return 2

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else Path.home() / ".transcriberpro"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TP_DATA_DIR"] = str(data_dir)
    if args.models_dir:
        os.environ["TP_MODELS_DIR"] = str(Path(args.models_dir).expanduser())

    # Import after the env vars: config and cache constants are evaluated on import.
    import uvicorn
    from utils.config import get_config
    from core.jobs.manager import JobManager
    from web.app import create_app

    config = get_config()
    manager = JobManager(
        target_language=config.get_target_language(),
        persist_path=data_dir / "jobs.json",
        log_dir=data_dir / "queue_logs",
        keep_alive=True,
    )
    app = create_app(manager, token=token, config=config)

    print(f"WebUI on http://{args.host}:{args.port}  (auth: {'on' if token else 'off'})")
    print(f"data: {data_dir}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
