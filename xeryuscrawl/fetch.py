"""Fetching one page safely. Every hop of a redirect is checked against the home-network rule before it is fetched, and
the address actually connected to is checked again; robots.txt and a per-site pace are kept by default. A page that asks for
a login, a captcha or a paywall comes back as blocked."""
import re
import threading
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

from . import config
from .guard import BrowserError, check_url

AGENT = config.AGENT
MAX_BYTES = 5_000_000
MAX_DOC_BYTES = 40_000_000  # PDFs and office files can be big
DOC_TYPES = ("pdf", "officedocument", "msword", "ms-excel", "ms-powerpoint", "opendocument")
RETRY_STATUS = (429, 500, 502, 503, 504)
_META_CHARSET = re.compile(rb"""<meta[^>]+charset=["']?([\w-]+)""", re.I)


def decode(body: bytes, content_type: str = "") -> str:
    """Text in the page's own encoding: a byte-order mark, the server's charset, the page's <meta charset>, then UTF-8,
    then Windows-1252 (what browsers assume)."""
    for bom, enc in ((bytes([0xEF, 0xBB, 0xBF]), "utf-8"), (bytes([0xFF, 0xFE]), "utf-16-le"), (bytes([0xFE, 0xFF]), "utf-16-be")):
        if body.startswith(bom):
            return body[len(bom):].decode(enc, errors="replace")
    m = re.search(r"charset=([\w-]+)", content_type, re.I)
    sniff = _META_CHARSET.search(body[:4096])
    for enc in [m.group(1) if m else None, sniff.group(1).decode("ascii", "ignore") if sniff else None]:
        if enc:
            try:
                return body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


MAX_HOPS = 5
BLOCK_MARKERS = ("captcha", "cf-challenge", "challenge-platform", "are you a robot", "verify you are human", "access denied")


class Blocked(Exception):
    """A page XeryusCrawl won't read: home-network address, robots.txt, login, captcha or paywall. The message is plain English."""


class Refused(Blocked):
    """Plain HTTP was turned away or timed out; an ordinary browser may still get the page (no evasion: the same name and
    rules), so the engine tries one before giving up."""


@dataclass
class Page:
    url: str
    status: int
    content_type: str
    text: str
    hops: list = field(default_factory=list)
    raw: bytes = b""
    retry_after: str = ""


class Fetcher:
    def __init__(self, http: httpx.Client | None = None, guard=check_url, pace: float = 1.0, robots: bool = True, clock=time.monotonic, sleep=time.sleep):
        self.http = http or httpx.Client(timeout=httpx.Timeout(20, connect=10), headers={"User-Agent": AGENT}, follow_redirects=False)
        self.guard, self.pace, self.robots, self.clock, self.sleep = guard, pace, robots, clock, sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self.host_pace: dict[str, float] = {}  # a crawl's own delay for one site
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def _check(self, url: str) -> None:
        try:
            self.guard(url)
        except BrowserError as exc:
            raise Blocked(f"That address can't be read: {exc}.") from exc

    def _wait_turn(self, host: str, delay: float) -> None:
        with self._lock:
            now = self.clock()
            ready = self._last.get(host, -1e9) + delay
            self._last[host] = max(now, ready)
        if ready > now:
            self.sleep(ready - now)

    def _rules(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        u = urlparse(url)
        site = f"{u.scheme}://{u.netloc}"
        if site not in self._robots:
            rules = None
            try:
                r = self._get(site + "/robots.txt", check_robots=False)
                if r.status < 400:
                    rules = urllib.robotparser.RobotFileParser()
                    rules.parse(r.text.splitlines())
                elif r.status in (401, 403):  # robots.txt itself refused: treat the site as closed
                    rules = urllib.robotparser.RobotFileParser()
                    rules.disallow_all = True
            except (Blocked, httpx.HTTPError):
                rules = None
            self._robots[site] = rules
        return self._robots[site]

    def allowed(self, url: str) -> bool:
        if not self.robots:
            return True
        rules = self._rules(url)
        return rules is None or rules.can_fetch(AGENT, url)

    def _get(self, url: str, check_robots: bool = True, headers: dict | None = None) -> Page:
        hops = []
        for _ in range(MAX_HOPS + 1):
            self._check(url)
            if check_robots and not self.allowed(url):
                raise Blocked("The site's robots.txt asks crawlers not to read this page.")
            host = urlparse(url).netloc
            rules = self._robots.get(f"{urlparse(url).scheme}://{host}") if check_robots else None
            delay = max(self.pace, self.host_pace.get(host, 0.0), float(rules.crawl_delay(AGENT) or 0) if rules else 0)
            if check_robots:  # reading robots.txt itself doesn't count as a visit (a long crawl-delay would hold up the first page)
                self._wait_turn(host, delay)
            with self.http.stream("GET", url, headers=headers or None) as r:
                peer = (r.extensions.get("network_stream").get_extra_info("server_addr") if r.extensions.get("network_stream") else None)
                if peer:  # the address really connected to, in case the name resolved differently a moment later
                    self._check(f"http://{peer[0]}/" if ":" not in peer[0] else f"http://[{peer[0]}]/")
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    hops.append(url)
                    url = urljoin(url, r.headers["location"])
                    continue
                ctype = r.headers.get("content-type", "")
                limit = MAX_DOC_BYTES if any(k in ctype.lower() for k in DOC_TYPES) else MAX_BYTES
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > limit:
                        break
                body = b"".join(chunks)[:limit]
                return Page(url=str(r.url), status=r.status_code, content_type=ctype, text=decode(body, ctype), hops=hops, raw=body,
                            retry_after=r.headers.get("retry-after", ""))
        raise Blocked("The page redirects too many times.")

    def get(self, url: str, retries: int = 3, headers: dict | None = None) -> Page:
        """With retries when the site is busy (429 and 5xx, and dropped connections), waiting as long as it asks (up to 30 s)
        or 1, 2, 4 seconds."""
        for attempt in range(retries + 1):
            try:
                page = self._get(url, headers=headers)
            except (httpx.TransportError,) as exc:
                if attempt >= min(retries, 1) or isinstance(exc, httpx.ReadTimeout):  # silent sites: one more try at most; a stalled one goes to the browser
                    raise Refused(f"The site didn't answer ({type(exc).__name__}).") from exc
                self.sleep(2 ** attempt)
                continue
            if page.status not in RETRY_STATUS or attempt == retries:
                break
            wait = float(page.retry_after) if page.retry_after.strip().isdigit() else 2 ** attempt
            self.sleep(min(wait, 30))
        low = page.text[:20000].lower()
        if page.status in (401, 407):
            raise Blocked("The page asks for a login.")
        if page.status in (402,) or page.status in (403, 429, 503) and any(m in low for m in BLOCK_MARKERS):
            raise Refused("The page is protected (a captcha, a robot check or a paywall), so XeryusCrawl leaves it.")
        return page
