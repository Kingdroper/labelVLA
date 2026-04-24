"""CLI entry point for ``labelvla_rs`` — LabelVLA remote-server."""

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from labelme.lerobot_server.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="labelvla_rs",
        description=(
            "Launch the LabelVLA remote annotation server. "
            "Serves a browser-based UI that mirrors the desktop `labelvla`."
        ),
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1; use 0.0.0.0 to expose on LAN).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000).",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Optional LeRobot dataset path to pre-load at startup.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable uvicorn auto-reload (development only).",
    )
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as e:
        raise SystemExit(
            "labelvla_rs requires 'fastapi' and 'uvicorn'. "
            "Install them with: pip install 'labelvla[server]' "
            "or pip install fastapi uvicorn"
        ) from e

    dataset_path = Path(args.dataset) if args.dataset else None
    app = create_app(dataset_path)

    logger.info(
        "LabelVLA remote server listening on http://{}:{}",
        args.host,
        args.port,
    )
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
