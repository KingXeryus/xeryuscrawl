"""Documents as well as web pages: XML, JSON, CSV, Markdown and plain text become Markdown the same way pages do, so every
tool (fit, chunks, schema and AI extraction) works on them. Sources: a web address, "raw:<html or text>", or a file inside
XeryusCrawl's own files folder (<home>/files); files anywhere else are refused."""
import csv
import io
import json
import re
import zipfile
from pathlib import Path

from lxml import etree

KINDS = {".xml": "xml", ".rss": "xml", ".atom": "xml", ".json": "json", ".csv": "csv", ".tsv": "tsv", ".md": "markdown",
         ".markdown": "markdown", ".txt": "text", ".html": "html", ".htm": "html", ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx",
         ".pptx": "pptx"}
BINARY = {"pdf", "docx", "xlsx", "pptx"}
OOXML = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
         "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
         "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx"}


def kind_of(name: str, content_type: str = "", text: str = "", raw: bytes = b"") -> str:
    ct = content_type.split(";")[0].strip().lower()
    by_type = {"application/json": "json", "text/csv": "csv", "text/tab-separated-values": "tsv", "text/markdown": "markdown",
               "text/plain": "text", "application/xml": "xml", "text/xml": "xml", "application/rss+xml": "xml", "application/atom+xml": "xml",
               "text/html": "html", "application/xhtml+xml": "html", "application/pdf": "pdf"} | OOXML
    if raw[:5] == b"%PDF-":
        return "pdf"
    if ct in by_type:
        return by_type[ct]
    ext = Path(name.split("?")[0]).suffix.lower()
    if ext in KINDS:
        return KINDS[ext]
    head = text.lstrip()[:200].lower()
    return "html" if head.startswith(("<!doctype html", "<html")) or "<body" in head else "xml" if head.startswith("<?xml") else "json" if head[:1] in "{[" else "text"


def _json_md(v, depth=0) -> str:
    pad = "  " * depth
    if isinstance(v, dict):
        return "\n".join(f"{pad}- **{k}**:" + ((" " + _scalar(x)) if not isinstance(x, (dict, list)) else "\n" + _json_md(x, depth + 1)) for k, x in v.items())
    if isinstance(v, list):
        return "\n".join(f"{pad}-" + ((" " + _scalar(x)) if not isinstance(x, (dict, list)) else "\n" + _json_md(x, depth + 1)) for x in v)
    return pad + _scalar(v)


def _scalar(x) -> str:
    return "null" if x is None else str(x)


def _xml_md(el, depth=0) -> list[str]:
    tag = etree.QName(el).localname if isinstance(el.tag, str) else ""
    text = (el.text or "").strip()
    attrs = " ".join(f'{etree.QName(k).localname}="{v}"' for k, v in el.attrib.items())
    lines = [f"{'  ' * depth}- **{tag}**" + (f" ({attrs})" if attrs else "") + (f": {text}" if text else "")] if tag else []
    for c in el:
        if isinstance(c.tag, str):
            lines += _xml_md(c, depth + 1)
    return lines


def to_markdown(text: str, kind: str) -> str:
    if kind in ("markdown", "text"):
        return text.strip()
    if kind == "json":
        return _json_md(json.loads(text))
    if kind in ("csv", "tsv"):
        rows = list(csv.reader(io.StringIO(text), delimiter="\t" if kind == "tsv" else ","))
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return ""
        width = max(map(len, rows))
        rows = [[c.replace("|", "\\|").strip() for c in r] + [""] * (width - len(r)) for r in rows]
        return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]])
    if kind == "xml":
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)  # no outside entities, no XXE
        return "\n".join(_xml_md(etree.fromstring(text.encode(), parser)))
    raise ValueError(f"not a document kind: {kind}")


def local_file(path: str, folder: Path) -> tuple[str, str]:
    """(text, name) of a file inside XeryusCrawl's own folder; anything outside it (or reached through a link) is refused."""
    p = Path(path.removeprefix("file:///").removeprefix("file://")).resolve()
    root = folder.resolve()
    if root not in p.parents or not p.is_file():
        raise PermissionError(f"XeryusCrawl reads files only from {root}")
    if p.stat().st_size > 20_000_000:
        raise ValueError("that file is too big (over 20 MB)")
    return p.read_text(encoding="utf-8", errors="replace"), p.name


# ── PDF and office files ──
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
MAX_PAGES = 500
MAX_ROWS = 2000


def _xml(zf, name: str):
    return etree.fromstring(zf.read(name), etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True))


def _md_table(rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(map(len, rows))
    rows = [[c.replace("|", r"\|").replace("\n", " ").strip() for c in r] + [""] * (width - len(r)) for r in rows]
    return "\n".join(["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]])


def pdf_markdown(raw: bytes) -> tuple[str, dict]:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001 - a password-protected PDF can't be read
            raise ValueError("the PDF is password-protected")
    info = reader.metadata or {}
    meta = {"title": str(info.get("/Title") or ""), "author": str(info.get("/Author") or ""), "pages": len(reader.pages)}
    parts = []
    for i, page in enumerate(reader.pages[:MAX_PAGES], 1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"## Page {i}\n\n{text}")
    if len(reader.pages) > MAX_PAGES:
        parts.append(f"(The first {MAX_PAGES} of {len(reader.pages)} pages.)")
    return "\n\n".join(parts), {k: v for k, v in meta.items() if v}


def docx_markdown(raw: bytes) -> tuple[str, dict]:
    zf = zipfile.ZipFile(io.BytesIO(raw))
    body = _xml(zf, "word/document.xml").find(f"{W}body")
    out = []
    for el in body:
        if el.tag == f"{W}p":
            text = "".join(t.text or "" for t in el.iter(f"{W}t")).strip()
            if not text:
                continue
            style = el.find(f"{W}pPr/{W}pStyle")
            name = (style.get(f"{W}val") if style is not None else "") or ""
            level = re.match(r"(?i)heading\s*([1-6])", name) or (re.match(r"(1)", "1") if name.lower() == "title" else None)
            bullet = el.find(f"{W}pPr/{W}numPr") is not None
            out.append(f"{'#' * int(level.group(1))} {text}" if level else f"- {text}" if bullet else text)
        elif el.tag == f"{W}tbl":
            rows = [["".join(t.text or "" for t in c.iter(f"{W}t")) for c in r.iter(f"{W}tc")] for r in el.iter(f"{W}tr")]
            out.append(_md_table(rows))
    meta = {}
    if "docProps/core.xml" in zf.namelist():
        core = _xml(zf, "docProps/core.xml")
        meta = {etree.QName(e).localname: e.text for e in core if e.text and etree.QName(e).localname in ("title", "creator", "subject")}
    return "\n\n".join(out), meta


def xlsx_markdown(raw: bytes) -> tuple[str, dict]:
    zf = zipfile.ZipFile(io.BytesIO(raw))
    shared = [("".join(t.text or "" for t in si.iter(f"{S}t"))) for si in _xml(zf, "xl/sharedStrings.xml")] if "xl/sharedStrings.xml" in zf.namelist() else []
    book = _xml(zf, "xl/workbook.xml")
    names = [s.get("name") for s in book.iter(f"{S}sheet")]
    sheets = sorted((n for n in zf.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    out = []
    for i, name in enumerate(sheets):
        rows = []
        for r in _xml(zf, name).iter(f"{S}row"):
            row = {}
            for c in r.iter(f"{S}c"):
                col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                v = c.find(f"{S}v")
                text = "".join(t.text or "" for t in c.iter(f"{S}t")) if c.get("t") == "inlineStr" else (v.text if v is not None else "")
                if c.get("t") == "s" and text and text.isdigit() and int(text) < len(shared):
                    text = shared[int(text)]
                row[idx] = text or ""
            if row:
                rows.append([row.get(j, "") for j in range(1, max(row) + 1)])
            if len(rows) >= MAX_ROWS:
                break
        title = names[i] if i < len(names) else f"Sheet {i + 1}"
        out.append(f"## {title}\n\n{_md_table(rows)}")
    return "\n\n".join(out), {"sheets": len(sheets)}


def pptx_markdown(raw: bytes) -> tuple[str, dict]:
    zf = zipfile.ZipFile(io.BytesIO(raw))
    slides = sorted((n for n in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
    out = []
    for i, name in enumerate(slides, 1):
        paras = ["".join(t.text or "" for t in p.iter(f"{A}t")).strip() for p in _xml(zf, name).iter(f"{A}p")]
        paras = [p for p in paras if p]
        if paras:
            out.append(f"## Slide {i}: {paras[0]}\n\n" + "\n".join(f"- {p}" for p in paras[1:]))
    return "\n\n".join(out), {"slides": len(slides)}


def binary_markdown(raw: bytes, kind: str) -> tuple[str, dict]:
    """(Markdown, details) of a PDF, Word, Excel or PowerPoint file."""
    try:
        return {"pdf": pdf_markdown, "docx": docx_markdown, "xlsx": xlsx_markdown, "pptx": pptx_markdown}[kind](raw)
    except (zipfile.BadZipFile, KeyError, etree.XMLSyntaxError) as exc:
        raise ValueError(f"that {kind.upper()} file couldn't be read ({type(exc).__name__})") from exc


def local_file_path(path: str, folder: Path) -> Path:
    """A file inside XeryusCrawl's own folder; anything outside it (or reached through a link) is refused."""
    p = Path(path.removeprefix("file:///").removeprefix("file://")).resolve()
    root = folder.resolve()
    if root not in p.parents or not p.is_file():
        raise PermissionError(f"XeryusCrawl reads files only from {root}")
    if p.stat().st_size > 40_000_000:
        raise ValueError("that file is too big (over 40 MB)")
    return p
