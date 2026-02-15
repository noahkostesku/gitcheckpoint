"""Entry point — run with ``python main.py``."""

import uvicorn

from src.api.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
