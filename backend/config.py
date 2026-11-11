"""Load the repository's local configuration without overriding shell variables."""

from pathlib import Path

from dotenv import load_dotenv


def load_local_env():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
