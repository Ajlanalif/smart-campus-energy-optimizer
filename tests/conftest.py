"""Project-level pytest configuration: load .env so tests can use the API key."""
from __future__ import annotations

import os

from dotenv import load_dotenv

# Load .env at the start of the test session so os.environ is populated.
load_dotenv()
