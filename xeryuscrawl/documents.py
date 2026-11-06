"""Documents as well as web pages: XML, JSON, CSV, Markdown and plain text become Markdown the same way pages do, so every
tool (fit, chunks, schema and AI extraction) works on them. Sources: a web address, "raw:<html or text>", or a file inside
XeryusCrawl's own files folder (<home>/files); files anywhere else are refused."""
import csv
import io
import json
from pathlib import Path

from lxml import etree

KINDS = {".xml": "xml", ".rss": "xml", ".atom": "xml", ".json": "json", ".csv": "csv", ".tsv": "tsv", ".md": "markdown",
         ".markdown": "markdown", ".txt": "text", ".html": "html", ".htm": "html"}


def kind_of(name: str, content_type: str = "", text: str = "") -> str:
    ct = content_type.split(";")[0].strip().lower()
    by_type = {"application/json": "json", "text/csv": "csv", "text/tab-separated-values": "tsv", "text/markdown": "markdown",
               "text/plain": "text", "application/xml": "xml", "text/xml": "xml", "application/rss+xml": "xml", "application/atom+xml": "xml",
               "text/html": "html", "application/xhtml+xml": "html"}
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
