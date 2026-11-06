"""XeryusCrawl's settings, all optional environment variables:

  XERYUSCRAWL_HOME         where the cache, jobs, sessions and readable files live (default ~/.xeryuscrawl)
  XERYUSCRAWL_SECRET_FILE  the service's secret, written at start (default <home>/crawl.secret)
  XERYUSCRAWL_PORT         the service's port on 127.0.0.1 (default 18102)
  XERYUSCRAWL_LLM_URL      a local OpenAI-compatible model server for AI extraction (default http://127.0.0.1:11434, Ollama;
                           LM Studio is http://127.0.0.1:1234, llama.cpp's server http://127.0.0.1:8080)
  XERYUSCRAWL_LLM_MODEL    the model's name there (default qwen3:8b)
  XERYUSCRAWL_SEARXNG      a SearXNG instance for web search (default http://127.0.0.1:8888)
  XERYUSCRAWL_VOICE        a text-to-speech service for spoken answers: POST /tts {"text", "voice"} -> {"audio": base64 WAV}
                           (off by default)
  XERYUSCRAWL_USER_AGENT   how the crawler names itself to websites
  PLAYWRIGHT_BROWSERS_PATH where Playwright's Chromium is installed (Playwright's own default otherwise)
"""
import os
from pathlib import Path

HOME = Path(os.environ.get("XERYUSCRAWL_HOME") or Path.home() / ".xeryuscrawl")
SECRET_FILE = Path(os.environ.get("XERYUSCRAWL_SECRET_FILE") or HOME / "crawl.secret")
PORT = int(os.environ.get("XERYUSCRAWL_PORT") or 18102)
URL = f"http://127.0.0.1:{PORT}"
LLM_URL = (os.environ.get("XERYUSCRAWL_LLM_URL") or "http://127.0.0.1:11434").rstrip("/")
LLM_MODEL = os.environ.get("XERYUSCRAWL_LLM_MODEL") or "qwen3:8b"
SEARXNG = (os.environ.get("XERYUSCRAWL_SEARXNG") or "http://127.0.0.1:8888").rstrip("/")
VOICE = (os.environ.get("XERYUSCRAWL_VOICE") or "").rstrip("/")
AGENT = os.environ.get("XERYUSCRAWL_USER_AGENT") or "XeryusCrawl/0.1 (+https://github.com/KingXeryus/xeryuscrawl; respects robots.txt)"
