"""Local dev server with auto-reload: `uv run python -m app.dev [--port 8000] [--worker]`.

Forces a selector event loop because psycopg's async driver can't run on Windows' default Proactor loop.
"""

import argparse

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--worker", action="store_true", help="run the Cloud Tasks worker app instead of the API")
    p.add_argument("--no-reload", action="store_true")
    a = p.parse_args()
    uvicorn.run(
        "app.main_worker:app" if a.worker else "app.main_api:app",
        host="127.0.0.1",
        port=a.port,
        reload=not a.no_reload,
        reload_dirs=["app"],
        loop="asyncio:SelectorEventLoop",
    )


if __name__ == "__main__":
    main()
