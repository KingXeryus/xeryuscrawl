"""XeryusCrawl's engine: one page in, the formats asked for out. Plain HTTP first; the browser when the page needs JavaScript
(or when asked). Results are cached. Everything a page says is untrusted: it is returned as data with "untrusted": true and
never acted on here.

Formats: markdown, fit_markdown (boilerplate removed, or only what matches `query`), html (the main content), rawHtml,
links (+ internal/external), media (images, videos, audio, frames), tables, citations (numbered references), screenshot,
pdf, json (schema or prompt through a local AI), chunks, summary (local AI), branding (colours, fonts, logo), changeTracking
(new, same or changed since the last visit, with a diff). Metadata is always there, with structured data (JSON-LD,
microdata), the canonical address and icons. PDF, Word, Excel and PowerPoint files are read like pages."""
import difflib
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config, documents, extract, filters, markdown, pageinfo
from .fetch import BLOCK_MARKERS, Blocked, Fetcher, Refused

FORMATS = {"markdown", "fit_markdown", "html", "rawHtml", "links", "media", "tables", "citations", "screenshot", "pdf", "json", "chunks",
           "summary", "branding", "changeTracking"}
NEEDS_JS = re.compile(r"enable javascript|requires javascript|<noscript>|id=\"(root|app|__next)\"\s*>\s*</div>", re.I)
MOBILE_AGENT = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"


def local_llm(messages: list, model: str | None = None, http: httpx.Client | None = None) -> str:
    """The configured model (config.py): a local OpenAI-compatible server, or a cloud provider with the user's own key."""
    provider, base = config.LLM_PROVIDER, config.LLM_URL
    if provider != "local" and not config.LLM_KEY:
        raise ValueError(f"set your {provider} API key first (xeryuscrawl setup, or XERYUSCRAWL_LLM_KEY)")
    body = {"model": model or config.LLM_MODEL, "messages": messages}
    if provider == "local":
        body |= {"temperature": 0, "max_tokens": 4000, "chat_template_kwargs": {"enable_thinking": False}}
    elif provider == "openai":
        body |= {"max_completion_tokens": 4000}
    else:
        body |= {"temperature": 0, "max_tokens": 4000}
    url = f"{base}/chat/completions" if base.endswith("/openai") and provider == "gemini" else f"{base}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {config.LLM_KEY}"} if config.LLM_KEY else {}
    r = (http or httpx.Client(timeout=900)).post(url, json=body, headers=headers)
    if r.status_code >= 400:
        raise ValueError(f"the model said {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"] or ""


def languages_header(location: dict | None) -> dict:
    """{"country": "CA", "languages": ["fr-CA", "en"]} -> an Accept-Language header."""
    langs = (location or {}).get("languages") or []
    if not langs and (location or {}).get("country"):
        langs = [f"en-{location['country'].upper()}", "en"]
    return {"Accept-Language": ", ".join(f"{l};q={1 - i / 10:.1f}" if i else l for i, l in enumerate(langs[:6]))} if langs else {}


class Engine:
    def __init__(self, data: Path, fetcher: Fetcher | None = None, render=None, llm=local_llm, clock=time.time):
        self.data, self.fetcher, self.llm, self.clock = data, fetcher or Fetcher(), llm, clock
        if render is None:
            from .render import render as real_render
            render = real_render
        self.render = render
        for d in ("cache", "files", "changes"):
            (data / d).mkdir(parents=True, exist_ok=True)

    # ── cache ──
    def _key(self, url: str, opts: dict) -> Path:
        body = json.dumps({"url": url, **{k: opts.get(k) for k in sorted(opts) if k not in ("max_age", "store")}}, sort_keys=True, default=str)
        return self.data / "cache" / (hashlib.sha256(body.encode()).hexdigest()[:40] + ".json")

    def scrape(self, url: str, formats: list | None = None, only_main: bool = True, query: str | None = None, render: str = "auto",
               max_age: int = 172800, store: bool = True, schema: dict | None = None, prompt: str | None = None, css_schema: dict | None = None,
               xpath_schema: dict | None = None, patterns: list | None = None, chunking: dict | None = None, include_tags: list | None = None,
               exclude_tags: list | None = None, location: dict | None = None, mobile: bool = False, **browser) -> dict:
        """render: "auto" (browser only when the page needs it), "always" or "never". include_tags / exclude_tags: CSS selectors
        of the parts to keep or remove. location: {"country", "languages"}. mobile: as a phone. browser: wait_for, wait_ms,
        actions, js_code, scan_full_page, headers, viewport, session, full_page, stealth, timeout_ms. max_age: seconds a cached
        copy is good for (0 = always fresh; changeTracking always reads fresh)."""
        formats = list(formats or ["markdown"])
        bad = set(formats) - FORMATS
        if bad:
            raise ValueError(f"unknown formats: {', '.join(sorted(bad))}")
        opts = {"formats": formats, "only_main": only_main, "query": query, "render": render, "schema": schema, "prompt": prompt,
                "css_schema": css_schema, "xpath_schema": xpath_schema, "patterns": patterns, "chunking": chunking, "include_tags": include_tags,
                "exclude_tags": exclude_tags, "location": location, "mobile": mobile, **browser}
        key = self._key(url, opts)
        if max_age and "changeTracking" not in formats and key.is_file() and self.clock() - key.stat().st_mtime < max_age:
            return json.loads(key.read_text(encoding="utf-8")) | {"cached": True}
        doc = self._scrape(url, opts, browser)
        if store:
            key.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    def _source(self, url: str, render: str, want_browser: bool, browser: dict, headers: dict) -> tuple[str, str, int, str, dict]:
        """(text, final url, status, kind, extras) from a web page, raw: text or a file in XeryusCrawl's folder."""
        if url.startswith("raw:"):
            text = url[4:]
            return text, "raw:", 200, documents.kind_of("", "", text), {}
        if url.startswith("file:"):
            path = documents.local_file_path(url, self.data / "files")
            raw = path.read_bytes()
            kind = documents.kind_of(path.name, "", "", raw)
            return ("" if kind in documents.BINARY else raw.decode("utf-8", errors="replace")), url, 200, kind, {"raw": raw}
        if urlparse(url).scheme not in ("http", "https"):
            raise Blocked("Only web addresses, raw: text and files in XeryusCrawl's folder can be read.")
        if render == "always" or want_browser:
            return self._browser(url, browser)
        try:
            page = self.fetcher.get(url, headers=headers or None)
        except Refused:
            if render == "never":
                raise
            text, final, status, kind, extras = self._browser(url, browser)  # turned away or timed out: try an ordinary browser
            if status in (401, 402, 403, 429, 503) and any(m in text[:20000].lower() for m in BLOCK_MARKERS):
                raise Blocked("The page is protected (a captcha, a robot check or a paywall), so XeryusCrawl leaves it.")
            return text, final, status, kind, extras
        kind = documents.kind_of(page.url, page.content_type, page.text, page.raw)
        if kind == "html" and render == "auto" and self._needs_js(page.text):
            return self._browser(url, browser)
        return ("" if kind in documents.BINARY else page.text), page.url, page.status, kind, {"raw": page.raw}

    def _browser(self, url: str, browser: dict):
        if not self.fetcher.allowed(url):
            raise Blocked("The site's robots.txt asks crawlers not to read this page.")
        r = self.render(url, guard=self.fetcher.guard, sessions=self.data / "sessions", **browser)
        extras = {k: r[k] for k in ("screenshot", "pdf", "js_results", "action_results") if k in r}
        return r["html"], r["url"], r["status"], "html", extras

    @staticmethod
    def _needs_js(html: str) -> bool:
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S | re.I)
        return len(text.split()) < 60 or bool(NEEDS_JS.search(html)) and len(text.split()) < 400

    def _changes(self, url: str, md: str) -> dict:
        """Compared with the last time this address was read (by any format that asked for changeTracking)."""
        f = self.data / "changes" / (hashlib.sha256(url.encode()).hexdigest()[:40] + ".json")
        prev = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
        f.write_text(json.dumps({"at": self.clock(), "markdown": md}), encoding="utf-8")
        if prev is None:
            return {"status": "new", "previousScrapeAt": None}
        if prev["markdown"] == md:
            return {"status": "same", "previousScrapeAt": prev["at"]}
        diff = "\n".join(list(difflib.unified_diff(prev["markdown"].splitlines(), md.splitlines(), "before", "now", lineterm="", n=1))[:400])
        return {"status": "changed", "previousScrapeAt": prev["at"], "diff": diff}

    def _scrape(self, url: str, o: dict, browser: dict) -> dict:
        formats, only_main, query = o["formats"], o["only_main"], o["query"]
        headers = languages_header(o["location"]) | ({"User-Agent": MOBILE_AGENT} if o["mobile"] else {}) | (browser.get("headers") or {})
        if o["location"] or o["mobile"]:
            browser = browser | {"locale": (o["location"] or {}).get("languages", [None])[0], "mobile": o["mobile"]}
        shots = {"screenshot": "screenshot" in formats, "pdf": "pdf" in formats}
        want_browser = any(shots.values()) or any(browser.get(k) for k in ("actions", "js_code", "wait_for", "scan_full_page", "session"))
        if any(shots.values()):
            browser = browser | shots
        text, final, status, kind, extras = self._source(url, o["render"], want_browser, browser, headers)
        raw = extras.pop("raw", b"")
        doc: dict = {"url": final, "untrusted": True, "metadata": {"sourceURL": url, "url": final, "statusCode": status, "kind": kind}}
        if kind == "html":
            text = pageinfo.keep_parts(text, o["include_tags"], o["exclude_tags"])
            conv = markdown.convert(text, final, only_main)
            root = markdown.parse(text)
            doc["metadata"] |= conv["metadata"] | pageinfo.details(text, final)
            md = conv["markdown"]
            if "links" in formats:
                doc["links"] = conv["links"]
                doc["linkGroups"] = markdown.split_links(conv["links"], final)
            if "media" in formats:
                doc["media"] = markdown.media(root, final)
            if "tables" in formats:
                doc["tables"] = markdown.tables(root)
            if "html" in formats:
                doc["html"] = filters.prune(text) if only_main else text
            if "fit_markdown" in formats:
                pruned = filters.prune(text)
                fit = markdown.convert(pruned or text, final, True)["markdown"]
                doc["fit_markdown"] = filters.fit(fit, query) if query else fit
            if "branding" in formats:
                sheets = []
                for css_url in pageinfo.stylesheet_links(text, final):
                    try:
                        sheets.append(self.fetcher.get(css_url, retries=0).text[:300_000])
                    except Exception:  # noqa: BLE001 - a stylesheet that can't be read is skipped
                        pass
                doc["branding"] = pageinfo.branding(text, final, sheets)
        else:
            if kind in documents.BINARY:
                md, meta = documents.binary_markdown(raw, kind)
                doc["metadata"] |= meta
            else:
                md = documents.to_markdown(text, kind)
            if "fit_markdown" in formats:
                doc["fit_markdown"] = filters.fit(md, query) if query else md
        if "rawHtml" in formats:
            doc["rawHtml"] = text
        if "markdown" in formats:
            doc["markdown"] = md
        if "citations" in formats:
            body, refs = filters.citations(md)
            doc["citations"] = {"markdown": body, "references": refs}
        if "chunks" in formats:
            c = o["chunking"] or {}
            parts = filters.chunk(md, c.get("how", "paragraph"), int(c.get("size", 200)), int(c.get("overlap", 50)), c.get("pattern"))
            if query:
                scores = filters.cosine(query, parts) if c.get("rank") == "cosine" else filters.bm25(query, parts)
                parts = [{"text": p, "score": round(s, 4)} for s, p in sorted(zip(scores, parts), key=lambda x: -x[0])]
            doc["chunks"] = parts
        if o["css_schema"]:
            doc["extracted"] = extract.by_schema(text, o["css_schema"], "css")
        if o["xpath_schema"]:
            doc["extracted"] = extract.by_schema(text, o["xpath_schema"], "xpath")
        if o["patterns"] is not None:
            doc["patterns"] = extract.by_patterns(md, o["patterns"] or None)
        if "changeTracking" in formats:
            doc["changeTracking"] = self._changes(final, md)
        if "json" in formats:
            doc["json"] = extract.with_ai(self.llm, [{"url": final, "markdown": doc.get("fit_markdown") or md}], prompt=o["prompt"], schema=o["schema"])
        if "summary" in formats:
            doc["summary"] = extract.with_ai(self.llm, [{"url": final, "markdown": doc.get("fit_markdown") or md}],
                                             prompt='a short, plain summary of the page in 3-6 sentences, as {"summary": "..."}').get("summary")
        doc |= extras
        return doc
