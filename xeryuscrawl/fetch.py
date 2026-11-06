"""Fetching one page safely. Every hop of a redirect is checked against the home-network rule before it is fetched, and
the address actually connected to is checked again; robots.txt and a per-site pace are kept by default. A page that asks for
a login, a captcha or a paywall comes back as blocked."""
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
MAX_HOPS = 5
BLOCK_MARKERS = ("captcha", "cf-challenge", "challenge-platform", "are you a robot", "verify you are human", "access denied")


class Blocked(Exception):
    """A page XeryusCrawl won't read: home-network address, robots.txt, login, captcha or paywall. The message is plain English."""


@dataclass
class Page:
    url: str
    status: int
    content_type: str
    text: str
    hops: list = field(default_factory=list)
    raw: bytes = b""


class Fetcher:
    def __init__(self, http: httpx.Client | None = None, guard=check_url, pace: float = 1.0, robots: bool = True, clock=time.monotonic, sleep=time.sleep):
        self.http = http or httpx.Client(timeout=30, headers={"User-Agent": AGENT}, follow_redirects=False)
        self.guard, self.pace, self.robots, self.clock, self.sleep = guard, pace, robots, clock, sleep
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
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

    def _get(self, url: str, check_robots: bool = True) -> Page:
        hops = []
        for _ in range(MAX_HOPS + 1):
            self._check(url)
            if check_robots and not self.allowed(url):
                raise Blocked("The site's robots.txt asks crawlers not to read this page.")
            host = urlparse(url).netloc
            rules = self._robots.get(f"{urlparse(url).scheme}://{host}") if check_robots else None
            delay = max(self.pace, float(rules.crawl_delay(AGENT) or 0) if rules else 0)
            self._wait_turn(host, delay)
            with self.http.stream("GET", url) as r:
                peer = (r.extensions.get("network_stream").get_extra_info("server_addr") if r.extensions.get("network_stream") else None)
                if peer:  # the address really connected to, in case the name resolved differently a moment later
                    self._check(f"http://{peer[0]}/" if ":" not in peer[0] else f"http://[{peer[0]}]/")
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    hops.append(url)
                    url = urljoin(url, r.headers["location"])
                    continue
                body = b""
                for chunk in r.iter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        break
                text = body[:MAX_BYTES].decode(r.encoding or "utf-8", errors="replace")
                return Page(url=str(r.url), status=r.status_code, content_type=r.headers.get("content-type", ""), text=text, hops=hops, raw=body[:MAX_BYTES])
        raise Blocked("The page redirects too many times.")

    def get(self, url: str) -> Page:
        page = self._get(url)
        low = page.text[:20000].lower()
        if page.status in (401, 407):
            raise Blocked("The page asks for a login.")
        if page.status in (402,) or page.status in (403, 429, 503) and any(m in low for m in BLOCK_MARKERS):
            raise Blocked("The page is protected (a captcha, a robot check or a paywall), so XeryusCrawl leaves it.")
        return page
