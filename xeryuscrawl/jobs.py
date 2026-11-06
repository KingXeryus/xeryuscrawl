"""Long work in the background: crawls and batches run as jobs. Each job's status, pages and resume point are saved under
<home>/jobs/<id>, so a job stopped by a restart carries on from where it was."""
import json
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class Jobs:
    def __init__(self, root: Path, crawler, workers: int = 2, clock=time.time):
        self.root, self.crawler, self.clock = root, crawler, clock
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(workers)
        self.stop_flags: dict[str, threading.Event] = {}
        self.lock = threading.Lock()

    def _dir(self, job: str) -> Path:
        if not job.isalnum() or len(job) > 40:
            raise KeyError(job)
        return self.root / job

    def _save(self, job: str, **fields) -> None:
        p = self._dir(job) / "job.json"
        with self.lock:
            info = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
            p.write_text(json.dumps(info | fields), encoding="utf-8")

    def _page(self, job: str, doc: dict) -> None:
        with self.lock, (self._dir(job) / "pages.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(doc) + "\n")

    def start(self, kind: str, params: dict, job: str | None = None) -> str:
        if kind not in ("crawl", "batch"):
            raise ValueError("a job is a crawl or a batch")
        job = job or secrets.token_hex(8)
        self._dir(job).mkdir(parents=True, exist_ok=True)
        self._save(job, id=job, kind=kind, params=params, state="running", started=self.clock(), done=0)
        flag = self.stop_flags.setdefault(job, threading.Event())
        flag.clear()
        self.pool.submit(self._run, job, kind, params)
        return job

    def _run(self, job: str, kind: str, params: dict) -> None:
        flag = self.stop_flags[job]
        count = {"n": 0}

        def on_page(doc):
            count["n"] += 1
            self._page(job, doc)
            self._save(job, done=count["n"])
        try:
            if kind == "crawl":
                state_file = self._dir(job) / "state.json"
                state = json.loads(state_file.read_text(encoding="utf-8")) if state_file.is_file() else None
                p = dict(params)
                url = p.pop("url")
                out = self.crawler.crawl(url, state=state, save=lambda st: state_file.write_text(json.dumps(st), encoding="utf-8"),
                                         on_page=on_page, should_stop=flag.is_set, **p)
                self._save(job, state="stopped" if out["stopped"] == "stopped" else "done", why=out["stopped"], finished=self.clock())
            else:
                p = dict(params)
                urls = p.pop("urls")
                self.crawler.batch(urls, on_page=on_page, should_stop=flag.is_set, **p)
                self._save(job, state="stopped" if flag.is_set() else "done", finished=self.clock())
        except Exception as exc:  # noqa: BLE001 - the caller sees why
            self._save(job, state="failed", why=str(exc)[:300], finished=self.clock())

    def status(self, job: str, skip: int = 0, limit: int = 50) -> dict:
        d = self._dir(job)
        if not (d / "job.json").is_file():
            raise KeyError(job)
        info = json.loads((d / "job.json").read_text(encoding="utf-8"))
        pages = []
        if (d / "pages.jsonl").is_file():
            with (d / "pages.jsonl").open(encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= skip + limit:
                        break
                    if i >= skip:
                        pages.append(json.loads(line))
        return info | {"data": pages, "next": skip + limit if len(pages) == limit else None}

    def stop(self, job: str) -> None:
        self._dir(job)
        self.stop_flags.setdefault(job, threading.Event()).set()

    def resume(self, job: str) -> str:
        info = self.status(job, 0, 0)
        if info["state"] == "running":
            return job
        return self.start(info["kind"], info["params"], job)

    def resume_unfinished(self) -> list[str]:
        """After a restart: jobs that were still running carry on."""
        out = []
        for d in self.root.iterdir():
            f = d / "job.json"
            if f.is_file() and json.loads(f.read_text(encoding="utf-8")).get("state") == "running":
                out.append(self.start(*(lambda i: (i["kind"], i["params"], i["id"]))(json.loads(f.read_text(encoding="utf-8")))))
        return out
