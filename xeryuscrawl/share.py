"""Sharing research passages (only when the user said yes at setup, XERYUSCRAWL_SHARE): the public web passages deep research
finds are kept in <home>/share/outbox.jsonl, with private details blanked, and sent in the background at most once a day.
What is sent: the passage, its web address and page title, and a random install id (stored by the receiver only as a hash).
Never: questions, searches, answers, API keys, files, or anything else on this computer. See TERMS.md."""
import json
import re
import threading
import time

import httpx

from . import config

PRIVATE = [  # blanked before anything is kept
    (re.compile(r"\b[\w.%+-]+@[a-z\d-]+(?:\.[a-z\d-]+)*\.[a-z]{2,}\b", re.I), "[email]"),
    (re.compile(r"(?<!\w)(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]?\d{3,4}[\s.-]?\d{3,4}(?!\w)"), "[phone]"),
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[number]"),
    (re.compile(r"\b(?:sk|pk|rk|ghp|gho|xox[abp]|AKIA)[-_A-Za-z0-9]{12,}\b"), "[key]"),
]
_lock = threading.Lock()


def scrub(text: str) -> str:
    for pat, rep in PRIVATE:
        text = pat.sub(rep, text)
    return text


def _outbox():
    d = config.HOME / "share"
    d.mkdir(parents=True, exist_ok=True)
    return d / "outbox.jsonl"


def keep(passages: list[dict], sources: list[dict]) -> int:
    """passages: [{"source": n, "text"}], sources: [{"n", "url", "title"}] from deep research. Returns how many were kept."""
    if not config.SHARE or not config.INSTALL_ID:
        return 0
    by_n = {s["n"]: s for s in sources}
    rows = []
    for p in passages:
        s = by_n.get(p.get("source"))
        text = scrub(p.get("text", "")).strip()
        if s and s["url"].startswith(("http://", "https://")) and 80 <= len(text) <= 2000:
            rows.append({"url": s["url"], "title": (s.get("title") or "")[:300], "text": text, "at": time.time()})
    if rows:
        with _lock, _outbox().open("a", encoding="utf-8") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    return len(rows)


def send(http: httpx.Client | None = None, force: bool = False) -> int:
    """Sends what is waiting (200 at a time), at most once a day unless forced. Returns how many were accepted."""
    if not config.SHARE or not config.INSTALL_ID:
        return 0
    box = _outbox()
    stamp = box.with_name("last-sent")
    if not box.is_file() or not force and stamp.is_file() and time.time() - stamp.stat().st_mtime < 86400:
        return 0
    with _lock:
        rows = [json.loads(x) for x in box.read_text(encoding="utf-8").splitlines() if x.strip()]
    sent = 0
    client = http or httpx.Client(timeout=30)
    for i in range(0, len(rows), 200):
        batch = rows[i:i + 200]
        try:
            r = client.post(config.SHARE_URL, json={"install": config.INSTALL_ID, "passages": [{k: x[k] for k in ("url", "title", "text")} for x in batch]})
        except httpx.HTTPError:
            break
        if r.status_code >= 400:
            break
        sent += len(batch)
    with _lock:
        left = [json.loads(x) for x in box.read_text(encoding="utf-8").splitlines() if x.strip()][sent:]
        box.write_text("".join(json.dumps(r) + "\n" for r in left), encoding="utf-8")
    stamp.touch()
    return sent


def send_later() -> None:
    threading.Thread(target=lambda: send(), daemon=True).start()
