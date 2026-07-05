"""Run the playground server: ``.venv/bin/python -m musicgen.playground``."""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="anoptic-musicgen playground server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--reload", action="store_true", help="dev auto-reload")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run("musicgen.playground.server:app", host=args.host, port=args.port,
                reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
