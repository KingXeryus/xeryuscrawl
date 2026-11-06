"""XeryusCrawl, beyond the basics: office files and PDFs, encodings, retries, structured data, page parts, branding, change
tracking, clean addresses, crawling under a folder in parallel, webhooks, cloud model keys, Brave search, the agent and setup."""
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from xeryuscrawl import config, smart
from xeryuscrawl import engine as eng
from xeryuscrawl.crawler import Crawler, normalize
from xeryuscrawl.documents import binary_markdown
from xeryuscrawl.fetch import Fetcher, decode
from xeryuscrawl.jobs import Jobs
from tests.test_crawl import GUARD, engine, fetcher, site

ROOT = Path(__file__).resolve().parents[1]


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buf.getvalue()


def _pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 6\n0000000000 65535 f \n" + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % xref


def test_pdf_word_excel_and_powerpoint_are_read(tmp_path):
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    docx = _zip({"word/document.xml": f'<w:document {w}><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Oud</w:t></w:r></w:p>'
                 '<w:p><w:r><w:t>Eleven strings.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t></w:r></w:p></w:tc>'
                 '<w:tc><w:p><w:r><w:t>B</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>'})
    md, _ = binary_markdown(docx, "docx")
    assert md.startswith("# Oud") and "Eleven strings." in md and "| A | B |" in md
    s = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    xlsx = _zip({"xl/workbook.xml": f'<workbook {s}><sheets><sheet name="Tunings" sheetId="1"/></sheets></workbook>',
                 "xl/sharedStrings.xml": f"<sst {s}><si><t>Name</t></si><si><t>Arabic</t></si></sst>",
                 "xl/worksheets/sheet1.xml": f'<worksheet {s}><sheetData><row><c r="A1" t="s"><v>0</v></c><c r="B1"><v>11</v></c></row>'
                                             '<row><c r="A2" t="s"><v>1</v></c><c r="B2"><v>6</v></c></row></sheetData></worksheet>'})
    md, meta = binary_markdown(xlsx, "xlsx")
    assert "## Tunings" in md and "| Arabic | 6 |" in md and meta["sheets"] == 1
    a = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    pptx = _zip({"ppt/slides/slide1.xml": f'<p:sld xmlns:p="x" {a}><a:p><a:r><a:t>Maqam</a:t></a:r></a:p><a:p><a:r><a:t>Rast</a:t></a:r></a:p></p:sld>'})
    assert binary_markdown(pptx, "pptx")[0] == "## Slide 1: Maqam\n\n- Rast"
    f = fetcher({})
    f.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"},
                                                                                 content=_pdf("Oud tuning C F A D G C"))))
    doc = engine(tmp_path, f).scrape("https://public.test/tuning.pdf", max_age=0)
    assert "Oud tuning C F A D G C" in doc["markdown"] and doc["metadata"]["kind"] == "pdf" and doc["metadata"]["pages"] == 1


def test_encodings_retries_and_clean_addresses():
    assert decode("café".encode("cp1252"), "text/html") == "café" and "مرحبا" in decode('<meta charset="windows-1256">مرحبا'.encode("cp1256"))
    calls, waits = [], []

    def handle(req):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "2"}) if len(calls) < 3 else httpx.Response(200, text="<p>ok</p>")
    f = Fetcher(http=httpx.Client(transport=httpx.MockTransport(handle)), guard=GUARD, pace=0, robots=False, sleep=waits.append)
    assert f.get("https://public.test/busy").status == 200 and waits == [2.0, 2.0]
    assert normalize("HTTPS://WWW.Public.test:443/a/?utm_source=x&b=2&a=1#top") == "https://public.test/a?a=1&b=2"
    assert normalize("https://public.test/a?b=1", ignore_query=True) == "https://public.test/a"


def test_structured_data_parts_branding_and_change_tracking(tmp_path):
    page = ('<html><head><title>T</title><link rel="canonical" href="/oud"><link rel="icon" href="/fav.png">'
            '<meta name="theme-color" content="#7c3aed"><style>body{color:#1a73e8;font-family:"Inter",sans-serif}</style>'
            '<script type="application/ld+json">{"@type":"Product","name":"Oud","offers":{"price":"499"}}</script></head><body>'
            '<div class="cookie-banner">Accept cookies</div><article><img src="/logo.svg" alt="Shop logo"><h1>Oud</h1><p>' + "Eleven strings. " * 80
            + '</p><div class="price">$499</div><div id="ad">Buy now</div></article></body></html>')
    state = {"text": page}
    f = fetcher({})
    f.http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=state["text"])))
    e = engine(tmp_path, f)
    doc = e.scrape("https://public.test/p", formats=["markdown", "branding", "changeTracking"], exclude_tags=["#ad"], max_age=0)
    assert doc["metadata"]["canonical"] == "https://public.test/oud" and doc["metadata"]["jsonLd"][0]["name"] == "Oud"
    assert "Buy now" not in doc["markdown"] and doc["branding"]["themeColor"] == "#7c3aed" and "#1a73e8" in doc["branding"]["colors"]
    assert doc["branding"]["fonts"] == ["Inter"] and doc["branding"]["logo"] == "https://public.test/logo.svg"
    assert doc["changeTracking"]["status"] == "new"
    assert e.scrape("https://public.test/p", formats=["markdown", "changeTracking"], exclude_tags=["#ad"])["changeTracking"]["status"] == "same"
    state["text"] = page.replace("$499", "$450")
    changed = e.scrape("https://public.test/p", formats=["markdown", "changeTracking"], exclude_tags=["#ad"])["changeTracking"]
    assert changed["status"] == "changed" and "$450" in changed["diff"]
    only = e.scrape("https://public.test/p", formats=["markdown"], include_tags=[".price"], only_main=False, max_age=0)
    assert only["markdown"].strip() == "$450"


def test_crawl_stays_under_its_folder_reads_in_parallel_and_calls_webhooks(tmp_path):
    routes = site() | {"https://public.test/a/1": (200, {"content-type": "text/html"}, "<article><p>" + "word " * 80
                                                   + "<a href='/b/1'>sibling</a><a href='/a/2?utm_source=x'>dup</a></p></article>")}
    c = Crawler(engine(tmp_path, fetcher(routes)))
    under = [p["url"] for p in c.crawl("https://public.test/a", limit=10, workers=3)["pages"]]
    assert all(u.startswith("https://public.test/a") for u in under) and len(under) == 3  # /a, /a/1, /a/2, each once
    assert len(c.crawl("https://public.test/a", limit=10, entire_domain=True)["pages"]) > 3
    hooks = []

    class Hooks:
        def post(self, url, json, headers, timeout):
            hooks.append(json["type"])
    jobs = Jobs(tmp_path / "jobs", c, http=Hooks())
    job = jobs.start("crawl", {"url": "https://public.test/", "limit": 3, "webhook": "https://hooks.test/x"})
    for _ in range(100):
        if jobs.status(job)["state"] != "running":
            break
        time.sleep(0.05)
    assert hooks[0] == "crawl.started" and hooks.count("crawl.page") == 3 and hooks[-1] == "crawl.completed"


def test_cloud_model_key_brave_search_agent_and_site_wide_answers(tmp_path, monkeypatch):
    seen = {}

    def handle(req):
        seen["url"], seen["auth"], seen["body"] = str(req.url), req.headers.get("authorization"), json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"answer": "11"}'}}]})
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_URL", "https://api.openai.com")
    monkeypatch.setattr(config, "LLM_KEY", "sk-test")
    assert eng.local_llm([{"role": "user", "content": "hi"}], http=httpx.Client(transport=httpx.MockTransport(handle))) == '{"answer": "11"}'
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == "Bearer sk-test" and "chat_template_kwargs" not in seen["body"]
    monkeypatch.setattr(config, "LLM_KEY", "")
    with pytest.raises(ValueError, match="API key"):
        eng.local_llm([{"role": "user", "content": "hi"}])
    monkeypatch.setattr(config, "SEARCH", "brave")
    monkeypatch.setattr(config, "BRAVE_KEY", "BSA-test")

    def brave_api(r):
        if r.headers.get("x-subscription-token") != "BSA-test":
            return httpx.Response(401)
        return httpx.Response(200, json={"web": {"results": [{"url": "https://public.test/a", "title": "A", "description": "d"}]}})
    assert smart.search("oud", 3, httpx.Client(transport=httpx.MockTransport(brave_api)), time_range="week") == [
        {"url": "https://public.test/a", "title": "A", "description": "d"}]
    e = engine(tmp_path, fetcher(site()), llm=lambda m: '{"answer": "eleven"}')
    sm = smart.Smart(e, Crawler(e))
    under = sm.expand(["https://public.test/a/*"])
    assert {"https://public.test/a/1", "https://public.test/a/2"} <= set(under) and all(u.startswith("https://public.test/a") for u in under)
    out = sm.agent("oud strings", urls=["https://public.test/"], max_pages=6)
    assert out["answer"] == {"answer": "eleven"} and out["sources"] and out["pages_read"] >= 1


def test_setup_saves_keys_and_status_hides_them(tmp_path):
    mod = "xeryuscrawl.cli" if (ROOT / "services").is_dir() else "xeryuscrawl.cli"
    env = {**__import__("os").environ, "XERYUSCRAWL_HOME": str(tmp_path), "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, "-m", mod, "setup", "--llm", "anthropic", "--llm-key", "sk-ant-secret-123", "--search", "brave",
                    "--brave-key", "BSA-secret-9"], env=env, stdin=subprocess.DEVNULL, capture_output=True, check=True)
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["XERYUSCRAWL_LLM_PROVIDER"] == "anthropic" and saved["XERYUSCRAWL_LLM_MODEL"] and saved["XERYUSCRAWL_BRAVE_KEY"] == "BSA-secret-9"
    out = subprocess.run([sys.executable, "-m", mod, "status"], env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120).stdout
    assert "sk-ant-secret-123" not in out and "BSA-secret-9" not in out and "anthropic" in out
