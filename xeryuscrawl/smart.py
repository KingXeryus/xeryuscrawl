"""Asking pages questions, all on a local model:
- ask: one page or many, a question or a JSON schema, one combined answer;
- search_answer: search the web, read the top results, answer from them with sources;
- speak: the answer read aloud by a text-to-speech service (XERYUSCRAWL_VOICE);
- script: a Python scraping script for pages like these, as text that is never run.
Web search goes through a SearXNG instance (XERYUSCRAWL_SEARXNG)."""
import base64
from urllib.parse import urlparse

import httpx

from . import config, extract

SEARXNG = config.SEARXNG
VOICE = config.VOICE


def search(query: str, limit: int = 5, http: httpx.Client | None = None, categories: str | None = None, time_range: str | None = None,
           language: str | None = None) -> list[dict]:
    """Web search through SearXNG or, with the user's own key, Brave Search. categories: general (default), news or images.
    time_range: day, week, month or year. language: e.g. en, fr, ar."""
    http = http or httpx.Client(timeout=30)
    if time_range not in (None, "day", "week", "month", "year"):
        raise ValueError("time_range is day, week, month or year")
    if config.SEARCH == "brave":
        if not config.BRAVE_KEY:
            raise ValueError("set your Brave Search API key first (xeryuscrawl setup, or XERYUSCRAWL_BRAVE_KEY)")
        kind = {"news": "news", "images": "images"}.get(categories or "", "web")
        params = {"q": query[:400], "count": min(limit, 20)} | ({"freshness": {"day": "pd", "week": "pw", "month": "pm", "year": "py"}[time_range]}
                                                               if time_range else {}) | ({"search_lang": language} if language else {})
        r = http.get(f"https://api.search.brave.com/res/v1/{kind}/search", params=params,
                     headers={"X-Subscription-Token": config.BRAVE_KEY, "Accept": "application/json"})
        r.raise_for_status()
        data = r.json()
        items = data.get("web", {}).get("results", []) if kind == "web" else data.get("results", [])
        return [{"url": x.get("url"), "title": x.get("title", ""), "description": x.get("description", ""),
                 **({"image": (x.get("properties") or {}).get("url")} if kind == "images" else {}), **({"date": x.get("age")} if x.get("age") else {})}
                for x in items[:limit] if x.get("url")]
    params = {"q": query[:400], "format": "json", "safesearch": 1} | ({"categories": categories} if categories else {})         | ({"time_range": time_range} if time_range else {}) | ({"language": language} if language else {})
    try:
        r = http.get(f"{SEARXNG}/search", params=params)
    except httpx.TransportError as exc:
        raise ValueError(f"no search engine at {SEARXNG}: run `xeryuscrawl install-search`, or use Brave (xeryuscrawl setup)") from exc
    r.raise_for_status()
    return [{"url": x["url"], "title": x.get("title", ""), "description": x.get("content", ""),
             **({"image": x.get("img_src")} if x.get("img_src") else {}), **({"date": x.get("publishedDate")} if x.get("publishedDate") else {})}
            for x in r.json().get("results", [])[:limit]]


class Smart:
    def __init__(self, engine, crawler, http: httpx.Client | None = None):
        self.engine, self.crawler, self.http = engine, crawler, http or httpx.Client(timeout=900)

    def _pages(self, sources: list[str], query: str | None) -> list[dict]:
        docs = self.crawler.batch(sources, formats=["markdown", "fit_markdown"], query=query)
        return [{"url": d["url"], "markdown": d.get("fit_markdown") or d.get("markdown", "")} for d in docs if not d.get("error")]

    def expand(self, sources: list[str], limit: int = 50) -> list[str]:
        """An address ending in /* means every page of the site under it (from its map)."""
        out = []
        for s in sources:
            if s.endswith("/*"):
                base = s[:-2]
                p = urlparse(base)
                site = self.crawler.map(f"{p.scheme}://{p.netloc}/", limit=limit * 20)
                found = [u for u in site if u == base or u.startswith(base.rstrip("/") + "/")]
                if len(found) < limit:  # no sitemap listing them: crawl the folder to find its pages
                    found += [d["url"] for d in self.crawler.crawl(base, limit=limit, max_depth=4)["pages"] if not d.get("error")]
                out += list(dict.fromkeys(found))[:limit]
            else:
                out.append(s)
        return list(dict.fromkeys(out))

    def ask(self, prompt: str | None, sources: list[str], schema: dict | None = None, web_search: bool = False, limit: int = 50) -> dict:
        """One answer from many pages. Sources may end in /* (the whole site under it); web_search adds the top search results."""
        sources = self.expand(sources, limit)
        if web_search and prompt:
            sources += [h["url"] for h in search(prompt, 5, self.http)]
        pages = self._pages(sources[:limit], prompt)
        if not pages:
            return {"answer": None, "sources": [], "note": "None of the pages could be read."}
        return {"answer": extract.with_ai(self.engine.llm, pages, prompt=prompt, schema=schema), "sources": [p["url"] for p in pages], "untrusted": True}

    def agent(self, prompt: str, urls: list[str] | None = None, schema: dict | None = None, max_pages: int = 25) -> dict:
        """Find the data a goal asks for: start from the given addresses (or a web search), crawl best-first toward pages that
        match the goal until they cover it, then extract the answer from the best of them."""
        starts = urls or [h["url"] for h in search(prompt, 3, self.http)]
        if not starts:
            return {"answer": None, "sources": [], "note": "Nothing to start from."}
        pages, per = [], max(3, max_pages // len(starts))
        for start in starts:
            out = self.crawler.crawl(start, strategy="best_first", limit=per, max_depth=3, query=prompt, entire_domain=True,
                                     scrape={"formats": ["markdown", "fit_markdown", "links"], "query": prompt})
            pages += [p for p in out["pages"] if not p.get("error") and (p.get("fit_markdown") or p.get("markdown"))]
        from . import filters
        ranked = sorted(pages, key=lambda p: -max(filters.bm25(prompt, [p.get("fit_markdown") or p["markdown"]] + [""]) or [0]))[:8]
        best = [{"url": p["url"], "markdown": p.get("fit_markdown") or p["markdown"]} for p in ranked]
        return {"answer": extract.with_ai(self.engine.llm, best, prompt=prompt, schema=schema), "sources": [b["url"] for b in best],
                "pages_read": len(pages), "untrusted": True}

    def search_answer(self, prompt: str, results: int = 5, schema: dict | None = None) -> dict:
        hits = search(prompt, results, self.http)
        out = self.ask(prompt, [h["url"] for h in hits], schema)
        return out | {"search": hits}

    def speak(self, prompt: str, sources: list[str], voice: str = "af_heart") -> dict:
        if not VOICE:
            raise ValueError("no text-to-speech service is set (XERYUSCRAWL_VOICE)")
        out = self.ask(prompt + " Answer in a few plain sentences, as {\"answer\": \"...\"}.", sources)
        text = out["answer"].get("answer") if isinstance(out["answer"], dict) else str(out["answer"])
        r = self.http.post(f"{VOICE}/tts", json={"text": (text or "I couldn't find an answer.")[:2000], "voice": voice})
        r.raise_for_status()
        return out | {"text": text, "audio": "data:audio/wav;base64," + r.json()["audio"]}

    def script(self, want: str, sources: list[str]) -> dict:
        """One script that handles every source given."""
        docs = self.crawler.batch(sources, formats=["rawHtml"], render="auto")
        sample = "\n\n".join(f"<!-- {d['url']} -->\n{d.get('rawHtml', '')[:20000 // max(1, len(docs))]}" for d in docs if not d.get("error"))
        code = extract.make_script(self.engine.llm, ", ".join(sources), sample, want)
        compile(code, "<script>", "exec")  # it must at least be valid Python; it is never run here
        return {"script": code, "sources": sources, "note": "Read it before running it: XeryusCrawl never runs scripts."}


def audio_bytes(data_uri: str) -> bytes:
    return base64.b64decode(data_uri.split(",", 1)[1])
