import os

MODEL_URL = os.getenv("MODEL_URL", "").strip()
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "").strip()
MODEL_NAME = os.getenv("MODEL_NAME", "").strip()

# The patterns of the urls that we want to pay attention to
URLS_OF_INTEREST = r"api\.github|copilot-codex"
