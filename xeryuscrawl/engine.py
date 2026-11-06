"""XeryusCrawl's engine: one page in, the formats asked for out. Plain HTTP first; the browser when the page needs JavaScript
(or when asked). Results are cached. Everything a page says is untrusted: it is returned as data with "untrusted": true and
never acted on here.

Formats: markdown, fit_markdown (boilerplate removed, or only what matches `query`), html (the main content), rawHtml,
links (+ internal/external), media (images, videos, audio, frames), tables, citations (numbered references), screenshot,
pdf, metadata (always), json (schema or prompt through a local AI), chunks."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from . import config, documents, extract, filters, markdown
from .fetch import Blocked, Fetcher

FORMATS = {"markdown", "fit_markdown", "html", "rawHtml", "links", "media", "tables", "citations", "screenshot", "pdf", "json", "chunks"}
SWAP = config.LLM_URL
MODEL = config.LLM_MODEL
NEEDS_JS = re.compile(r"enable javascript|requires javascript|<noscript>|id=\"(root|app|__next)\"\s*>\s*</div>", re.I)


def local_llm(messages: list, model: str = MODEL, http: httpx.Client | None = None) -> str:
    """The local model through llama-swap (the GPU broker loads it). Never a cloud model."""
    r = (http or httpx.Client(timeout=900)).post(f"{SWAP}/v1/chat/completions", json={
        "model": model, "messages": messages, "temperature": 0, "max_tokens": 4000, "chat_template_kwargs": {"enable_thinking": False}})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


class Engine:
    def __init__(self, data: Path, fetcher: Fetcher | None = None, render=None, llm=local_llm, clock=time.time):
        self.data, self.fetcher, self.llm, self.clock = data, fetcher or Fetcher(), llm, clock
        if render is None:
            from .render import render as real_render
            render = real_render
        self.render = render
        (data / "cache").mkdir(parents=True, exist_ok=True)
        (data / "files").mkdir(parents=True, exist_ok=True)

    # ── cache ──
    def _key(self, url: str, opts: dict) -> Path:
        body = json.dumps({"url": url, **{k: opts.get(k) for k in sorted(opts) if k not in ("max_age", "store")}}, sort_keys=True, default=str)
        return self.data / "cache" / (hashlib.sha256(body.encode()).hexdigest()[:40] + ".json")

    def scrape(self, url: str, formats: list | None = None, only_main: bool = True, query: str | None = None, render: str = "auto",
               max_age: int = 172800, store: bool = True, schema: dict | None = None, prompt: str | None = None, css_schema: dict | None = None,
               xpath_schema: dict | None = None, patterns: list | None = None, chunking: dict | None = None, **browser) -> dict:
        """render: "auto" (browser only when the page needs it), "always" or "never". browser: wait_for, actions, js_code,
        scan_full_page, headers, viewport, session, full_page, stealth, timeout_ms. max_age: seconds a cached copy is good for (0 = fresh)."""
        formats = list(formats or ["markdown"])
        bad = set(formats) - FORMATS
        if bad:
            raise ValueError(f"unknown formats: {', '.join(sorted(bad))}")
        opts = {"formats": formats, "only_main": only_main, "query": query, "render": render, "schema": schema, "prompt": prompt,
                "css_schema": css_schema, "xpath_schema": xpath_schema, "patterns": patterns, "chunking": chunking, **browser}
        key = self._key(url, opts)
        if max_age and key.is_file() and self.clock() - key.stat().st_mtime < max_age:
            return json.loads(key.read_text(encoding="utf-8")) | {"cached": True}
        doc = self._scrape(url, formats, only_main, query, render, schema, prompt, css_schema, xpath_schema, patterns, chunking, browser)
        if store:
            key.write_text(json.dumps(doc), encoding="utf-8")
        return doc

    def _source(self, url: str, render: str, want_browser: bool, browser: dict) -> tuple[str, str, int, str, dict]:
        """(text, final url, status, kind, extras) from a web page, raw: text or a file in XeryusCrawl's folder."""
        if url.startswith("raw:"):
            text = url[4:]
            return text, "raw:", 200, documents.kind_of("", "", text), {}
        if url.startswith("file:"):
            text, name = documents.local_file(url, self.data / "files")
            return text, url, 200, documents.kind_of(name, "", text), {}
        if urlparse(url).scheme not in ("http", "https"):
            raise Blocked("Only web addresses, raw: text and files in XeryusCrawl's folder can be read.")
        if render == "always" or want_browser:
            return self._browser(url, browser)
        page = self.fetcher.get(url)
        kind = documents.kind_of(page.url, page.content_type, page.text)
        if kind == "html" and render == "auto" and self._needs_js(page.text):
            return self._browser(url, browser)
        return page.text, page.url, page.status, kind, {}

    def _browser(self, url: str, browser: dict):
        if not self.fetcher.allowed(url):
            raise Blocked("The site's robots.txt asks crawlers not to read this page.")
        r = self.render(url, guard=self.fetcher.guard, sessions=self.data / "sessions", **browser)
        extras = {k: r[k] for k in ("screenshot", "pdf", "js_results") if k in r}
        return r["html"], r["url"], r["status"], "html", extras

    @staticmethod
    def _needs_js(html: str) -> bool:
        text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S | re.I)
        return len(text.split()) < 60 or bool(NEEDS_JS.search(html)) and len(text.split()) < 400

    def _scrape(self, url, formats, only_main, query, render, schema, prompt, css_schema, xpath_schema, patterns, chunking, browser) -> dict:
        shots = {"screenshot": "screenshot" in formats, "pdf": "pdf" in formats}
        want_browser = any(shots.values()) or any(browser.get(k) for k in ("actions", "js_code", "wait_for", "scan_full_page", "session"))
        if any(shots.values()):
            browser = browser | shots
        text, final, status, kind, extras = self._source(url, render, want_browser, browser)
        doc: dict = {"url": final, "untrusted": True, "metadata": {"sourceURL": url, "url": final, "statusCode": status, "kind": kind}}
        if kind == "html":
            conv = markdown.convert(text, final, only_main)
            root = markdown.parse(text)
            doc["metadata"] |= conv["metadata"]
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
            c = chunking or {}
            parts = filters.chunk(md, c.get("how", "paragraph"), int(c.get("size", 200)), int(c.get("overlap", 50)), c.get("pattern"))
            if query:
                scores = filters.cosine(query, parts) if c.get("rank") == "cosine" else filters.bm25(query, parts)
                parts = [{"text": p, "score": round(s, 4)} for s, p in sorted(zip(scores, parts), key=lambda x: -x[0])]
            doc["chunks"] = parts
        if css_schema:
            doc["extracted"] = extract.by_schema(text, css_schema, "css")
        if xpath_schema:
            doc["extracted"] = extract.by_schema(text, xpath_schema, "xpath")
        if patterns is not None:
            doc["patterns"] = extract.by_patterns(md, patterns or None)
        if "json" in formats:
            doc["json"] = extract.with_ai(self.llm, [{"url": final, "markdown": doc.get("fit_markdown") or md}], prompt=prompt, schema=schema)
        doc |= extras
        return doc
