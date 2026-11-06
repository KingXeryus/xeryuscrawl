"""Asking pages questions, all on a local model:
- ask: one page or many, a question or a JSON schema, one combined answer;
- search_answer: search the web, read the top results, answer from them with sources;
- speak: the answer read aloud by a text-to-speech service (XERYUSCRAWL_VOICE);
- script: a Python scraping script for pages like these, as text that is never run.
Web search goes through a SearXNG instance (XERYUSCRAWL_SEARXNG)."""
import base64

import httpx

from . import config, extract

SEARXNG = config.SEARXNG
VOICE = config.VOICE


def search(query: str, limit: int = 5, http: httpx.Client | None = None, categories: str | None = None) -> list[dict]:
    params = {"q": query[:400], "format": "json", "safesearch": 1} | ({"categories": categories} if categories else {})
    r = (http or httpx.Client(timeout=30)).get(f"{SEARXNG}/search", params=params)
    r.raise_for_status()
    return [{"url": x["url"], "title": x.get("title", ""), "description": x.get("content", "")} for x in r.json().get("results", [])[:limit]]


class Smart:
    def __init__(self, engine, crawler, http: httpx.Client | None = None):
        self.engine, self.crawler, self.http = engine, crawler, http or httpx.Client(timeout=900)

    def _pages(self, sources: list[str], query: str | None) -> list[dict]:
        docs = self.crawler.batch(sources, formats=["markdown", "fit_markdown"], query=query)
        return [{"url": d["url"], "markdown": d.get("fit_markdown") or d.get("markdown", "")} for d in docs if not d.get("error")]

    def ask(self, prompt: str | None, sources: list[str], schema: dict | None = None) -> dict:
        pages = self._pages(sources, prompt)
        if not pages:
            return {"answer": None, "sources": [], "note": "None of the pages could be read."}
        return {"answer": extract.with_ai(self.engine.llm, pages, prompt=prompt, schema=schema), "sources": [p["url"] for p in pages], "untrusted": True}

    def search_answer(self, prompt: str, results: int = 5, schema: dict | None = None) -> dict:
        hits = search(prompt, results, self.http)
        out = self.ask(prompt, [h["url"] for h in hits], schema)
        return out | {"search": hits}

    def speak(self, prompt: str, sources: list[str], voice: str = "af_heart") -> dict:
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
