"""Many pages: map a site, crawl it, read a batch, and find addresses.

- map: the site's sitemaps (from robots.txt and /sitemap.xml, sitemap indexes followed) plus the links on its pages.
- crawl: breadth-first, depth-first or best-first (pages scored by keywords, depth and freshness), with include/exclude
  rules, a page limit and a depth limit; it saves its place after every page so a stopped crawl resumes where it was.
  With a question, it stops on its own once the pages read cover it.
- batch: many addresses at once, as many in parallel as free memory allows.
- seeds: sitemaps, and optionally the public Common Crawl index; subdomains from Certificate Transparency logs (crt.sh)."""
import ctypes
import gzip
import heapq
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

from lxml import etree

from . import filters
from .fetch import Blocked

SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|ico|css|js|mjs|woff2?|ttf|eot|mp3|mp4|webm|avi|mov|zip|gz|tar|rar|7z|exe|msi|dmg|iso|bin)(\?|$)", re.I)
DATE_IN_URL = re.compile(r"/(20\d{2})[/-](\d{1,2})?")


def _host(u: str) -> str:
    return (urlparse(u).hostname or "").removeprefix("www.")


def same_site(u: str, root: str, subdomains: bool) -> bool:
    h, r = _host(u), _host(root)
    return h == r or subdomains and h.endswith("." + r)


TRACKING = re.compile(r"^(utm_[a-z]+|gclid|fbclid|msclkid|mc_cid|mc_eid|_ga|yclid|igshid|ref_src|spm)$", re.I)


def normalize(u: str, ignore_query: bool = False, key: bool = True) -> str:
    """One spelling per page: no fragment, no tracking parameters, lower-case scheme and host, no default port, sorted query.
    key=True also drops "www." and a trailing slash, for spotting duplicates."""
    u = urldefrag(u)[0]
    p = urlparse(u)
    host = (p.hostname or "").lower()
    port = f":{p.port}" if p.port and not (p.scheme == "http" and p.port == 80 or p.scheme == "https" and p.port == 443) else ""
    query = "" if ignore_query else urlencode(sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not TRACKING.match(k)))
    path = p.path or "/"
    if key:
        host, path = host.removeprefix("www."), path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), host + port, path, "", query, ""))


def free_memory_gb() -> float:
    """Free memory on this PC (Windows), for deciding how many pages to read at once."""
    class MS(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong), ("c", ctypes.c_ulonglong),
                    ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
    try:
        s = MS(); s.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return s.ullAvailPhys / 2**30
    except (AttributeError, OSError):
        return 8.0


def workers_for_memory(asked: int | None = None, per_page_gb: float = 0.5, keep_free_gb: float = 4.0) -> int:
    """Never so many pages at once that the computer runs short of memory."""
    fit = int(max(0.0, free_memory_gb() - keep_free_gb) / per_page_gb)
    return max(1, min(asked or 8, fit, 16))


class Crawler:
    def __init__(self, engine):
        self.engine = engine
        self.fetcher = engine.fetcher

    # ── discovery ──
    def sitemaps(self, url: str, limit: int = 50000) -> list[str]:
        site = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        queue, seen, found = [], set(), []
        try:
            robots = self.fetcher.get(site + "/robots.txt").text
            queue += [ln.split(":", 1)[1].strip() for ln in robots.splitlines() if ln.lower().startswith("sitemap:")]
        except (Blocked, Exception):  # noqa: BLE001 - no robots.txt is fine
            pass
        queue += [site + "/sitemap.xml", site + "/sitemap_index.xml"]
        while queue and len(found) < limit and len(seen) < 200:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            try:
                page = self.fetcher.get(sm)
                if page.status >= 400:
                    continue
                body = gzip.decompress(page.raw) if page.raw[:2] == bytes([0x1F, 0x8B]) else page.raw or page.text.encode()
                root = etree.fromstring(body, etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
            except Exception:  # noqa: BLE001 - a broken sitemap is skipped
                continue
            if root is None:
                continue
            locs = [e.text.strip() for e in root.iter() if isinstance(e.tag, str) and etree.QName(e).localname == "loc" and e.text]
            if etree.QName(root).localname == "sitemapindex":
                queue += locs
            else:
                found += locs
        return list(dict.fromkeys(found))[:limit]

    def common_crawl(self, url: str, limit: int = 1000) -> list[str]:
        """Addresses Common Crawl has seen for this site (a public index; asked only when wanted)."""
        info = json.loads(self.fetcher.get("https://index.commoncrawl.org/collinfo.json").text)
        api = info[0]["cdx-api"]
        page = self.fetcher.get(f"{api}?url={_host(url)}/*&output=json&limit={int(limit)}&fl=url")
        return list(dict.fromkeys(json.loads(ln)["url"] for ln in page.text.splitlines() if ln.strip()))[:limit]

    def subdomains(self, url: str) -> list[str]:
        """Subdomains from public Certificate Transparency logs (crt.sh); asked only when wanted."""
        page = self.fetcher.get(f"https://crt.sh/?q=%25.{_host(url)}&output=json")
        names = {n.strip().lower().lstrip("*.") for row in json.loads(page.text or "[]") for n in row.get("name_value", "").split("\n")}
        return sorted(n for n in names if n.endswith(_host(url)))

    def feeds(self, url: str, limit: int = 2000) -> list[str]:
        """Article addresses from the site's RSS and Atom feeds (the ones its pages announce, and the usual places)."""
        site = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
        found, cands = [], []
        try:
            from . import pageinfo
            cands += pageinfo.details(self.fetcher.get(url).text, url).get("feeds", [])
        except Exception:  # noqa: BLE001 - a page without feeds is fine
            pass
        cands += [site + p for p in ("/feed", "/rss", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml")]
        for f in dict.fromkeys(cands):
            try:
                page = self.fetcher.get(f, retries=0)
                if page.status >= 400:
                    continue
                root = etree.fromstring(page.raw or page.text.encode(), etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
            except Exception:  # noqa: BLE001
                continue
            if root is None:
                continue
            for e in root.iter():
                if not isinstance(e.tag, str):
                    continue
                name = etree.QName(e).localname
                if name == "link" and (e.get("href") or (e.text or "").strip()):
                    found.append(urljoin(f, e.get("href") or e.text.strip()))
            if len(found) >= limit:
                break
        return list(dict.fromkeys(found))[:limit]

    def map(self, url: str, search: str | None = None, limit: int = 5000, include_subdomains: bool = False, sitemap: str = "include",
            common_crawl: bool = False, feeds: bool = True, ignore_query: bool = False) -> list[str]:
        """sitemap: "include" (sitemaps, feeds and page links), "only" or "skip". search: rank addresses by how well they match."""
        urls = [] if sitemap == "skip" else self.sitemaps(url, limit)
        if sitemap != "only":
            doc = self.engine.scrape(url, formats=["links"], only_main=False)
            urls += doc.get("links", [])
            if feeds:
                urls += self.feeds(url)
        if common_crawl:
            urls += self.common_crawl(url, limit)
        keyed = {}
        for u in urls:
            if u.startswith(("http://", "https://")) and same_site(u, url, include_subdomains):
                keyed.setdefault(normalize(u, ignore_query), normalize(u, ignore_query, key=False))
        urls = list(keyed.values())
        if search:
            scores = filters.bm25(search, [re.sub(r"[/_.?=&-]+", " ", urlparse(u).path + " " + urlparse(u).query) for u in urls])
            urls = [u for s, u in sorted(zip(scores, urls), key=lambda x: -x[0])]
        return urls[:limit]

    # ── crawling ──
    @staticmethod
    def score(url: str, depth: int, keywords: list[str], anchor: str = "") -> float:
        """Best-first: keywords in the address or link text, shallow pages and recent dates score higher."""
        text = (url + " " + anchor).lower()
        kw = sum(1 for k in keywords if k.lower() in text) / max(1, len(keywords)) if keywords else 0
        m = DATE_IN_URL.search(url)
        fresh = 0.2 if m and int(m.group(1)) >= 2024 else 0
        return kw + 1 / (1 + depth) * 0.3 + fresh

    def crawl(self, url: str, strategy: str = "bfs", limit: int = 50, max_depth: int = 3, include_paths: list | None = None,
              exclude_paths: list | None = None, keywords: list | None = None, include_subdomains: bool = False, allow_external: bool = False,
              entire_domain: bool = False, ignore_query: bool = False, workers: int = 4, delay: float | None = None,
              query: str | None = None, confidence: float = 0.8, state: dict | None = None, save=None, on_page=None, should_stop=None,
              scrape: dict | None = None) -> dict:
        """Returns {"pages": [...], "state": {...}, "stopped": reason}. save(state) is called after every page (resume with state=).
        entire_domain: also pages outside the start address's own folder (by default only those under it). workers: pages read
        at once (depth-first reads one at a time). delay: seconds between pages of one site."""
        if strategy not in ("bfs", "dfs", "best_first"):
            raise ValueError("strategy is bfs, dfs or best_first")
        inc = [re.compile(p) for p in include_paths or []]
        exc = [re.compile(p) for p in exclude_paths or []]
        keywords = keywords or (filters.words(query) if query else [])
        start_path = urlparse(url).path or "/"
        base_path = start_path if start_path.endswith("/") else start_path + "/"  # /blog means /blog and /blog/...
        st = state or {"frontier": [[0.0, 0, url, ""]], "seen": [normalize(url, ignore_query)], "done": 0, "covered": {}}
        seen = set(st["seen"])
        pages, opts = [], {"formats": ["markdown", "links"]} | (scrape or {})
        if "links" not in opts["formats"]:
            opts["formats"] = list(opts["formats"]) + ["links"]
        if delay is not None:
            self.fetcher.host_pace[urlparse(url).netloc] = float(delay)
        width = 1 if strategy == "dfs" else max(1, min(int(workers or 1), 16))
        stopped = "finished"

        def read(u):
            try:
                return self.engine.scrape(u, **opts)
            except Exception as exc_:  # noqa: BLE001 - one bad page doesn't stop the crawl
                return {"url": u, "error": str(exc_)[:300], "untrusted": True}
        with ThreadPoolExecutor(width) as pool:
            while st["frontier"] and st["done"] < limit:
                if should_stop and should_stop():
                    stopped = "stopped"
                    break
                take = []
                while st["frontier"] and len(take) < min(width, limit - st["done"]):
                    if strategy == "bfs":
                        take.append(st["frontier"].pop(0))
                    elif strategy == "dfs":
                        take.append(st["frontier"].pop())
                    else:
                        heapq.heapify(st["frontier"])
                        take.append(heapq.heappop(st["frontier"]))
                docs = list(pool.map(lambda item: read(item[2]), take))
                enough = False
                for (_, depth, u, _a), doc in zip(take, docs):
                    st["done"] += 1
                    doc["depth"] = depth
                    pages.append(doc)
                    if on_page:
                        on_page(doc)
                    if query and doc.get("markdown"):  # adaptive: which question words the pages so far cover, and how often
                        terms = filters.words(query)
                        for w in terms:
                            st["covered"][w] = st["covered"].get(w, 0) + doc["markdown"].lower().count(w)
                        if terms and sum(1 for w in terms if st["covered"].get(w, 0) >= 3) / len(terms) >= confidence:
                            enough = True
                    if depth >= max_depth:
                        continue
                    for link in doc.get("links", []):
                        key = normalize(link, ignore_query)
                        if key in seen or SKIP_EXT.search(link):
                            continue
                        if not (allow_external or same_site(link, url, include_subdomains)):
                            continue
                        path = urlparse(link).path or "/"
                        outside = not (path == start_path or path.startswith(base_path))
                        if outside and not (entire_domain or allow_external) and same_site(link, url, include_subdomains):
                            continue
                        if inc and not any(r.search(path) for r in inc) or any(r.search(path) for r in exc):
                            continue
                        seen.add(key)
                        prio = -self.score(link, depth + 1, keywords) if strategy == "best_first" else 0.0
                        st["frontier"].append([prio, depth + 1, normalize(link, ignore_query, key=False), ""])
                st["seen"] = sorted(seen)
                if save:
                    save(st)
                if enough:
                    stopped = "enough to answer the question"
                    break
        if stopped == "finished" and st["done"] >= limit:
            stopped = "page limit reached"
        return {"pages": pages, "state": st, "stopped": stopped}

    def batch(self, urls: list[str], workers: int | None = None, on_page=None, should_stop=None, **scrape) -> list[dict]:
        out: list = [None] * len(urls)
        lock = threading.Lock()

        def one(i, u):
            if should_stop and should_stop():
                return
            try:
                doc = self.engine.scrape(u, **scrape)
            except Exception as exc:  # noqa: BLE001 - one bad page doesn't stop the batch
                doc = {"url": u, "error": str(exc)[:300], "untrusted": True}
            with lock:
                out[i] = doc
            if on_page:
                on_page(doc)
        with ThreadPoolExecutor(workers_for_memory(workers)) as pool:
            list(pool.map(lambda a: one(*a), enumerate(urls)))
        return [d for d in out if d is not None]


def load_state(p: Path) -> dict | None:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
