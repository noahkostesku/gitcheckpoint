"""Shared pytest configuration — loads .env before test collection."""

from dotenv import load_dotenv

# Load .env so that skip guards like `os.getenv("ANTHROPIC_API_KEY")`
# see the real values (not just shell-exported vars).
load_dotenv()
