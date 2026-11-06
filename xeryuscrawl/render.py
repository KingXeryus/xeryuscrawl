"""The browser: pages that build their text with JavaScript are opened in a headless Chromium. Every request the page makes
(frames, scripts, redirects) is checked against the home-network rule, so a public page can't reach into this computer or
its network through the browser. Also: screenshots and PDFs, page actions, your own JavaScript, waiting for an element,
scrolling the whole page (infinite scroll, lazy images), and sessions that keep cookies between calls.
Stealth mode, off unless asked: the browser looks like an ordinary Chrome (no webdriver flag, a normal user agent and
languages). Never proxies, never saved logins."""
STEALTH_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-CA', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
"""
import base64
import json
import os
import re
import threading
from pathlib import Path

from .guard import BrowserError, check_url

from . import config
LOCK = threading.Semaphore(2)  # at most two pages open at once
ACTIONS = {"wait", "click", "scroll", "type", "press", "javascript", "wait_for"}
SESSION = re.compile(r"^[a-z0-9-]{1,40}$")
AGENT = config.AGENT


def render(url: str, guard=check_url, wait_ms: int = 1000, screenshot: bool = False, full_page: bool = False, pdf: bool = False,
           actions: list | None = None, js_code: list | None = None, wait_for: str | None = None, scan_full_page: bool = False,
           headers: dict | None = None, viewport: dict | None = None, session: str | None = None, sessions: Path | None = None,
           stealth: bool = False, timeout_ms: int = 30000) -> dict:
    """{"html", "url", "status", "screenshot"?, "pdf"?, "js_results"?}. Actions: {"type": "wait", "milliseconds"},
    {"type": "click", "selector"}, {"type": "scroll", "direction"}, {"type": "type", "selector", "text"}, {"type": "press", "key"},
    {"type": "javascript", "script"}, {"type": "wait_for", "selector"}. A session id keeps cookies and storage between calls."""
    from playwright.sync_api import sync_playwright

    refused = []

    def gate(route):
        u = route.request.url
        if u.startswith(("data:", "blob:")):
            return route.continue_()
        if not u.startswith(("http://", "https://")):
            return route.abort()
        try:
            guard(u)
        except BrowserError:
            refused.append(u)
            return route.abort()
        return route.continue_()

    state = None
    if session:
        if not SESSION.match(session) or sessions is None:
            raise ValueError("a session name is lowercase letters, digits and dashes")
        state = sessions / f"{session}.json"
    with LOCK, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"] if stealth else [])
        try:
            ctx = browser.new_context(user_agent=STEALTH_UA if stealth else AGENT, locale="en-CA" if stealth else None, accept_downloads=False, service_workers="block",
                                      viewport={"width": int((viewport or {}).get("width", 1280)), "height": int((viewport or {}).get("height", 900))},
                                      extra_http_headers={str(k): str(v) for k, v in (headers or {}).items()},
                                      storage_state=str(state) if state and state.is_file() else None)
            ctx.route("**/*", gate)
            if stealth:
                ctx.add_init_script(STEALTH_JS)
            page = ctx.new_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if url in refused:
                raise BrowserError("that address is on this PC or the home network, which is off limits")
            try:
                page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 8000))
            except Exception:  # noqa: BLE001 - pages that never go quiet still have their text by now
                pass
            if wait_for:
                page.wait_for_selector(wait_for, timeout=min(timeout_ms, 15000))
            page.wait_for_timeout(min(wait_ms, 10000))
            results = [page.evaluate(code) for code in (js_code or [])[:10]]
            for a in (actions or [])[:30]:
                kind = a.get("type")
                if kind not in ACTIONS:
                    raise ValueError(f"unknown page action: {kind}")
                if kind == "wait":
                    page.wait_for_timeout(min(int(a.get("milliseconds", 1000)), 10000))
                elif kind == "click":
                    page.click(str(a["selector"]), timeout=5000)
                elif kind == "scroll":
                    page.mouse.wheel(0, -2000 if a.get("direction") == "up" else 2000)
                elif kind == "type":
                    page.fill(str(a["selector"]), str(a.get("text", "")), timeout=5000)
                elif kind == "press":
                    page.keyboard.press(str(a["key"]))
                elif kind == "javascript":
                    results.append(page.evaluate(str(a["script"])))
                elif kind == "wait_for":
                    page.wait_for_selector(str(a["selector"]), timeout=10000)
                page.wait_for_timeout(300)
            if scan_full_page:  # scroll to the bottom until the page stops growing: infinite scroll and lazy images
                last = 0
                for _ in range(40):
                    height = page.evaluate("document.body ? document.body.scrollHeight : 0")
                    if height == last:
                        break
                    last = height
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(600)
            out = {"html": page.content(), "url": page.url, "status": resp.status if resp else 200}
            if out["url"] != url:
                guard(out["url"])  # where the page ended up after its own scripts moved it
            if results:
                out["js_results"] = json.loads(json.dumps(results, default=str))
            if screenshot:
                out["screenshot"] = "data:image/png;base64," + base64.b64encode(page.screenshot(full_page=full_page)).decode()
            if pdf:
                out["pdf"] = "data:application/pdf;base64," + base64.b64encode(page.pdf(print_background=True)).decode()
            if state:
                state.parent.mkdir(parents=True, exist_ok=True)
                ctx.storage_state(path=str(state))
            return out
        finally:
            browser.close()
