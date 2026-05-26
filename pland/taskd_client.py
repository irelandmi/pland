"""HTTP client for the taskd REST API."""
from __future__ import annotations

import os

import httpx

DEFAULT_URL = "http://localhost:3000"


def base_url() -> str:
	return os.environ.get("TASKD_URL", DEFAULT_URL)


def _client() -> httpx.Client:
	return httpx.Client(base_url=base_url(), timeout=30)
