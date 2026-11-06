"""XeryusCrawl's service: REST on 127.0.0.1 (port 18102 by default). Only this computer can call it, and only with the
secret written to the secret file at start (see config.py).

    xeryuscrawl [--port 18102] [--data <folder>]"""
import argparse
import hmac
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import config, extract
from .crawler import Crawler
from .engine import Engine
from .fetch import Blocked
from .jobs import Jobs
from .research import deep_research
from .smart import Smart, search

# camelCase spellings accepted for the same options
ALIASES = {"onlyMainContent": "only_main", "maxAge": "max_age", "waitFor": "wait_for", "jsCode": "js_code", "scanFullPage": "scan_full_page",
           "fullPage": "full_page", "maxDepth": "max_depth", "includePaths": "include_paths", "excludePaths": "exclude_paths",
           "allowExternalLinks": "allow_external", "includeSubdomains": "include_subdomains", "cssSchema": "css_schema", "xpathSchema": "xpath_schema",
           "includeTags": "include_tags", "excludeTags": "exclude_tags", "crawlEntireDomain": "entire_domain", "ignoreQueryParameters": "ignore_query",
           "maxConcurrency": "workers", "enableWebSearch": "web_search", "timeRange": "time_range"}
SCRAPE_KEYS = {"formats", "only_main", "query", "render", "max_age", "store", "schema", "prompt", "css_schema", "xpath_schema", "patterns",
               "chunking", "wait_for", "wait_ms", "actions", "js_code", "scan_full_page", "headers", "viewport", "session", "full_page", "stealth", "timeout_ms",
               "include_tags", "exclude_tags", "location", "mobile"}
CRAWL_KEYS = {"url", "strategy", "limit", "max_depth", "include_paths", "exclude_paths", "keywords", "include_subdomains", "allow_external", "query",
              "confidence", "entire_domain", "ignore_query", "workers", "delay", "webhook"}


def opts(body: dict, keys: set) -> dict:
    out = {ALIASES.get(k, k): v for k, v in body.items()}
    if "max_age" in out and isinstance(out["max_age"], int) and out["max_age"] > 10**6:  # given in milliseconds
        out["max_age"] //= 1000
    if isinstance(out.get("wait_for"), int):  # a number is milliseconds to wait; a string is an element to wait for
        out["wait_ms"] = out.pop("wait_for")
    bad = set(out) - keys
    if bad:
        raise HTTPException(400, f"unknown options: {', '.join(sorted(bad))}")
    return out


def build_app(engine: Engine, secret: str) -> FastAPI:
    app = FastAPI(title="XeryusCrawl")
    crawler = Crawler(engine)
    jobs = Jobs(engine.data / "jobs", crawler)
    smart = Smart(engine, crawler)
    app.state.jobs = jobs

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        if request.headers.get("host", "").rsplit(":", 1)[0] not in ("127.0.0.1", "localhost") or request.headers.get("origin"):
            return JSONResponse({"detail": "refused"}, 403)
        return await call_next(request)

    def caller(x_crawl_secret: str = Header("")) -> None:
        if not hmac.compare_digest(x_crawl_secret, secret):
            raise HTTPException(403, "refused")

    @app.exception_handler(Blocked)
    async def blocked(_: Request, exc: Blocked):
        return JSONResponse({"success": False, "blocked": True, "error": str(exc)}, 200)

    @app.exception_handler(ValueError)
    async def bad_value(_: Request, exc: ValueError):
        return JSONResponse({"success": False, "error": str(exc)}, 400)

    @app.exception_handler(PermissionError)
    async def not_allowed(_: Request, exc: PermissionError):
        return JSONResponse({"success": False, "error": str(exc)}, 403)

    d = [Depends(caller)]

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/v2/scrape", dependencies=d)
    def scrape(body: dict):
        url = body.pop("url", "")
        return {"success": True, "data": engine.scrape(url, **opts(body, SCRAPE_KEYS))}

    @app.post("/v2/map", dependencies=d)
    def site_map(body: dict):
        o = {ALIASES.get(k, k): v for k, v in body.items()}
        return {"success": True, "links": crawler.map(o.pop("url"), **{k: o[k] for k in ("search", "limit", "include_subdomains", "sitemap", "common_crawl",
                                                                                       "feeds", "ignore_query") if k in o})}

    @app.post("/v2/subdomains", dependencies=d)
    def subdomains(body: dict):
        return {"success": True, "subdomains": crawler.subdomains(body["url"])}

    @app.post("/v2/crawl", dependencies=d)
    def crawl(body: dict):
        scrape_opts = opts(body.pop("scrapeOptions", body.pop("scrape", {})) or {}, SCRAPE_KEYS)
        params = opts(body, CRAWL_KEYS) | ({"scrape": scrape_opts} if scrape_opts else {})
        return {"success": True, "id": jobs.start("crawl", params)}

    @app.post("/v2/batch/scrape", dependencies=d)
    def batch(body: dict):
        urls = body.pop("urls", [])
        if not urls or len(urls) > 10000:
            raise HTTPException(400, "give between 1 and 10,000 addresses")
        return {"success": True, "id": jobs.start("batch", {"urls": urls} | opts(body, SCRAPE_KEYS | {"workers", "webhook"}))}

    for kind in ("crawl", "batch/scrape"):
        @app.get(f"/v2/{kind}/{{job}}", dependencies=d)
        def status(job: str, skip: int = 0, limit: int = 50):
            try:
                return {"success": True} | jobs.status(job, skip, min(limit, 500))
            except KeyError:
                raise HTTPException(404, "no such job")

        @app.delete(f"/v2/{kind}/{{job}}", dependencies=d)
        def cancel(job: str):
            jobs.stop(job)
            return {"success": True, "status": "stopping"}

        @app.post(f"/v2/{kind}/{{job}}/resume", dependencies=d)
        def resume(job: str):
            try:
                return {"success": True, "id": jobs.resume(job)}
            except KeyError:
                raise HTTPException(404, "no such job")

    @app.post("/v2/search", dependencies=d)
    def web_search(body: dict):
        b = {ALIASES.get(k, k): v for k, v in body.items()}
        cats = b.get("categories") or next((s for s in b.get("sources", []) if s in ("news", "images")), None)
        hits = search(b["query"], int(b.get("limit", 5)), categories=cats, time_range=b.get("time_range"), language=b.get("language"))
        so = body.get("scrapeOptions")
        if so:
            docs = crawler.batch([h["url"] for h in hits], **opts(dict(so), SCRAPE_KEYS))
            by_url = {d["url"]: d for d in docs}
            hits = [h | {"page": by_url.get(h["url"])} for h in hits]
        return {"success": True, "data": hits}

    @app.post("/v2/extract", dependencies=d)
    def ai_extract(body: dict):
        b = {ALIASES.get(k, k): v for k, v in body.items()}
        return {"success": True, "data": smart.ask(b.get("prompt"), b.get("urls", []), b.get("schema"), bool(b.get("web_search")))}

    @app.post("/v2/agent", dependencies=d)
    def agent(body: dict):
        return {"success": True, "data": smart.agent(body["prompt"], body.get("urls"), body.get("schema"), int(body.get("max_pages", 25)))}

    @app.post("/v2/ask", dependencies=d)
    def ask(body: dict):
        return {"success": True, "data": smart.ask(body["prompt"], body["urls"], body.get("schema"))}

    @app.post("/v2/search-answer", dependencies=d)
    def search_answer(body: dict):
        return {"success": True, "data": smart.search_answer(body["prompt"], int(body.get("results", 5)), body.get("schema"))}

    @app.post("/v2/speak", dependencies=d)
    def speak(body: dict):
        return {"success": True, "data": smart.speak(body["prompt"], body["urls"], body.get("voice", "af_heart"))}

    @app.post("/v2/script", dependencies=d)
    def script(body: dict):
        return {"success": True, "data": smart.script(body["want"], body["urls"])}

    @app.post("/v2/research", dependencies=d)
    def research(body: dict):
        keys = {"question", "queries", "breadth", "depth", "max_pages", "passages_per_page", "max_chars", "time_limit", "answer"}
        bad = set(body) - keys
        if bad or not str(body.get("question", "")).strip():
            raise HTTPException(400, "give a question" if not bad else f"unknown options: {', '.join(sorted(bad))}")
        return {"success": True, "data": deep_research(engine, crawler, **body)}

    @app.post("/v2/schema", dependencies=d)
    def make_schema(body: dict):
        doc = engine.scrape(body["url"], formats=["rawHtml"])
        return {"success": True, "schema": extract.make_schema(engine.llm, doc["rawHtml"], body["want"], body.get("kind", "css"))}

    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=config.PORT)
    ap.add_argument("--data", type=Path, default=config.HOME)
    ap.add_argument("--secret-file", type=Path, default=config.SECRET_FILE)
    a = ap.parse_args()
    secret = secrets.token_hex(32)
    a.secret_file.parent.mkdir(parents=True, exist_ok=True)
    a.secret_file.write_text(secret, encoding="ascii")
    engine = Engine(a.data)
    app = build_app(engine, secret)
    app.state.jobs.resume_unfinished()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
