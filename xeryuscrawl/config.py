"""XeryusCrawl's settings. `xeryuscrawl setup` writes them to <home>/config.json; environment variables override that file.

  XERYUSCRAWL_HOME          where the cache, jobs, sessions, files and config.json live (default ~/.xeryuscrawl)
  XERYUSCRAWL_PORT          the optional REST service's port on 127.0.0.1 (default 18102)

  The AI model, for answers, extraction and summaries (optional: crawling, search and deep research work without one):
  XERYUSCRAWL_LLM_PROVIDER  a cloud provider with your own API key: openrouter, openai, anthropic, gemini, groq or deepseek;
                            or local, a model server on this computer (Ollama, LM Studio, llama.cpp). Not set until
                            `xeryuscrawl setup`, which asks for it
  XERYUSCRAWL_LLM_KEY       your own API key for a cloud provider
  XERYUSCRAWL_LLM_URL       the server's address (each provider has its default; local: http://127.0.0.1:11434, Ollama)
  XERYUSCRAWL_LLM_MODEL     the model's name (each provider has its default)

  Web search (for search, deep research and search-answer):
  XERYUSCRAWL_SEARCH        searxng (default) or brave
  XERYUSCRAWL_SEARXNG       the SearXNG address (default http://127.0.0.1:8888; `xeryuscrawl install-search` sets one up)
  XERYUSCRAWL_BRAVE_KEY     your own Brave Search API key, when XERYUSCRAWL_SEARCH is brave

  XERYUSCRAWL_SHARE         yes or no (default no): share the public web passages your research finds with myMAK.ai,
                            to help train its AI models (see TERMS.md). Never your questions, keys or files. `xeryuscrawl sharing on|off`

  XERYUSCRAWL_VOICE         a text-to-speech service for spoken answers: POST /tts {"text", "voice"} -> {"audio": base64 WAV}
  XERYUSCRAWL_USER_AGENT    how the crawler names itself to websites
  XERYUSCRAWL_SECRET_FILE   the REST service's secret (default <home>/crawl.secret)
  PLAYWRIGHT_BROWSERS_PATH  where Playwright's Chromium is installed (Playwright's own default otherwise)
"""
import json
import os
from pathlib import Path

HOME = Path(os.environ.get("XERYUSCRAWL_HOME") or Path.home() / ".xeryuscrawl")
CONFIG_FILE = HOME / "config.json"
PROVIDERS = {  # provider -> (OpenAI-compatible base address, default model)
    "local": ("http://127.0.0.1:11434", "qwen3:8b"),
    "openai": ("https://api.openai.com", "gpt-5-mini"),
    "anthropic": ("https://api.anthropic.com", "claude-sonnet-5-5"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash"),
    "openrouter": ("https://openrouter.ai/api", "openai/gpt-5-mini"),
    "groq": ("https://api.groq.com/openai", "llama-3.3-70b-versatile"),
    "deepseek": ("https://api.deepseek.com", "deepseek-chat"),
}


def _file() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _get(name: str, default=None):
    return os.environ.get(name) or _file().get(name) or default


SECRET_FILE = Path(_get("XERYUSCRAWL_SECRET_FILE") or HOME / "crawl.secret")
PORT = int(_get("XERYUSCRAWL_PORT") or 18102)
URL = f"http://127.0.0.1:{PORT}"
LLM_PROVIDER = (_get("XERYUSCRAWL_LLM_PROVIDER") or "").lower()  # "" until setup: the AI features then ask for a key
if LLM_PROVIDER and LLM_PROVIDER not in PROVIDERS:
    raise SystemExit(f"XERYUSCRAWL_LLM_PROVIDER must be one of: {', '.join(PROVIDERS)}")
LLM_KEY = _get("XERYUSCRAWL_LLM_KEY") or ""
LLM_URL = (_get("XERYUSCRAWL_LLM_URL") or PROVIDERS.get(LLM_PROVIDER, ("",))[0]).rstrip("/")
LLM_MODEL = _get("XERYUSCRAWL_LLM_MODEL") or PROVIDERS.get(LLM_PROVIDER, ("", ""))[1]
SEARCH = (_get("XERYUSCRAWL_SEARCH") or "searxng").lower()
SEARXNG = (_get("XERYUSCRAWL_SEARXNG") or "http://127.0.0.1:8888").rstrip("/")
BRAVE_KEY = _get("XERYUSCRAWL_BRAVE_KEY") or ""
VOICE = (_get("XERYUSCRAWL_VOICE") or "").rstrip("/")
AGENT = _get("XERYUSCRAWL_USER_AGENT") or "XeryusCrawl/0.2 (+https://github.com/KingXeryus/xeryuscrawl; respects robots.txt)"
SHARE = str(_get("XERYUSCRAWL_SHARE") or "no").lower() in ("yes", "true", "1", "on")
SHARE_URL = _get("XERYUSCRAWL_SHARE_URL") or "https://gfcijjrzjhnyhntkbynj.supabase.co/functions/v1/research-share"
INSTALL_ID = _get("XERYUSCRAWL_INSTALL_ID") or ""
