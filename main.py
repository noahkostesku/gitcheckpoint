"""Entry point — run with ``python main.py``."""

import os

import uvicorn

from src.api.server import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
