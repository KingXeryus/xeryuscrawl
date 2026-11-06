"""Fit Markdown and chunks: keep a page's real content and drop menus and boilerplate, or keep only the parts that match a
question; split long pages into chunks and rank them (BM25 or TF-IDF cosine)."""
import math
import re
from collections import Counter

from lxml import etree
from lxml import html as lhtml

DROP_TAGS = ("script", "style", "noscript", "template", "iframe", "form", "nav", "header", "footer", "aside", "button", "select", "dialog")
BOILERPLATE = re.compile(r"(^|[\s_-])(nav|menu|footer|header|sidebar|cookie|consent|banner|advert|ads?|promo|share|social|breadcrumb|related|"
                         r"comments?|newsletter|popup|modal|subscribe)([\s_-]|$)", re.I)
KEEP_SHORT = {"h1", "h2", "h3", "h4", "h5", "h6", "th", "td", "dt", "caption", "figcaption", "code", "pre"}
_PARSER = lhtml.HTMLParser(huge_tree=True)
WORD = re.compile(r"[\w']+", re.U)
STOP = set("a an and are as at be but by for from has have he her his i in is it its of on or our she that the their them they this to was we were what when which who will with you your".split())


def _text(el) -> tuple[int, int]:
    """(visible characters, characters inside links) of an element."""
    total = len("".join(el.itertext()).strip())
    links = sum(len("".join(a.itertext()).strip()) for a in el.iter("a"))
    return total, links


def prune(html: str, max_link_share: float = 0.5, min_chars: int = 30) -> str:
    """The page's HTML with menus, banners, link lists and other boilerplate removed: page furniture by tag, role and
    class/id names; then any block that is mostly links, or too short to say anything and not a heading or table cell."""
    try:
        root = lhtml.document_fromstring(html, parser=_PARSER)
    except (etree.ParserError, etree.LxmlError, ValueError):
        return ""
    body = root.find("body")
    body = root if body is None else body
    etree.strip_elements(body, etree.Comment, *DROP_TAGS, with_tail=False)
    for el in list(body.iter()):
        if not isinstance(el.tag, str) or el is body or el.getparent() is None:
            continue
        hint = f"{el.get('class', '')} {el.get('id', '')}"
        if el.get("aria-hidden") == "true" or el.get("role") in ("navigation", "banner", "contentinfo", "complementary", "search") or                 el.tag not in ("article", "main") and BOILERPLATE.search(hint):
            el.drop_tree()
    blocks = ("div", "section", "ul", "ol", "dl", "table", "p")  # judged whole: never single links, words or cells
    for el in sorted((e for e in body.iter(*blocks) if e is not body), key=lambda e: -len(list(e.iterancestors()))):
        if el.getparent() is None:
            continue
        total, links = _text(el)
        if total == 0 and el.find(".//img") is None and el.tag != "img":
            el.drop_tree()
        elif total and (links / total > 0.8 or links / total > max_link_share and total < 600):  # link lists, menus
            el.drop_tree()
        elif el.tag in ("p", "div", "section") and total < min_chars and el.find(".//img") is None and                 not any(d.tag in KEEP_SHORT for d in el.iter()) and el.getparent().tag not in ("ul", "ol", "table", "tr"):
            el.drop_tree()
    return "".join(lhtml.tostring(el, encoding="unicode", with_tail=False) for el in body
                   if isinstance(el.tag, str) and any(x.strip() for x in el.itertext()))


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if w not in STOP]


def bm25(query: str, docs: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    q, toks = words(query), [words(d) for d in docs]
    if not q or not toks:
        return [0.0] * len(docs)
    avg = sum(map(len, toks)) / len(toks) or 1
    df = Counter(w for t in toks for w in set(t))
    out = []
    for t in toks:
        tf = Counter(t)
        out.append(sum(math.log(1 + (len(toks) - df[w] + 0.5) / (df[w] + 0.5)) * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
                       for w in q if w in tf))
    return out


def cosine(query: str, docs: list[str]) -> list[float]:
    """TF-IDF cosine similarity of each chunk to the question."""
    toks = [Counter(words(d)) for d in docs]
    n = len(docs)
    df = Counter(w for t in toks for w in t)
    idf = {w: math.log((1 + n) / (1 + c)) + 1 for w, c in df.items()}
    qv = {w: c * idf.get(w, 1.0) for w, c in Counter(words(query)).items()}
    qn = math.sqrt(sum(v * v for v in qv.values())) or 1
    out = []
    for t in toks:
        dv = {w: c * idf[w] for w, c in t.items()}
        dn = math.sqrt(sum(v * v for v in dv.values())) or 1
        out.append(sum(v * dv.get(w, 0) for w, v in qv.items()) / (qn * dn))
    return out


def chunk(text: str, how: str = "paragraph", size: int = 200, overlap: int = 50, pattern: str | None = None) -> list[str]:
    """paragraph (blank lines), heading (Markdown sections, the page's own topics), sentence, regex (your pattern),
    words (fixed windows of `size` words) or sliding (windows of `size` words overlapping by `overlap`)."""
    if how == "paragraph":
        parts = re.split(r"\n\s*\n", text)
    elif how == "heading":
        parts = re.split(r"\n(?=#{1,6} )", "\n" + text)
    elif how == "sentence":
        parts = re.split(r"(?<=[.!?。！？])\s+(?=[A-Z0-9\"'(؀-ۿ一-鿿])", text)
    elif how == "regex":
        parts = re.split(pattern or r"\n\n", text)
    elif how in ("words", "sliding"):
        w = text.split()
        step = size if how == "words" else max(1, size - overlap)
        parts = [" ".join(w[i:i + size]) for i in range(0, max(len(w), 1), step)]
    else:
        raise ValueError(f"unknown chunking: {how}")
    return [p.strip() for p in parts if p and p.strip()]


def fit(markdown: str, query: str | None = None, top: int | None = None, threshold: float = 0.3) -> str:
    """With a question: the paragraphs that match it (BM25 score at least `threshold` of the best one, best `top` kept,
    in page order)."""
    if not query:
        return markdown
    parts = chunk(markdown, "paragraph")
    scores = bm25(query, parts)
    best = max(scores, default=0)
    keep = [i for i, s in enumerate(scores) if s > 0 and s >= threshold * best]
    if top:
        keep = sorted(sorted(keep, key=lambda i: -scores[i])[:top])
    return "\n\n".join(parts[i] for i in keep)


def citations(markdown: str) -> tuple[str, str]:
    """Links become numbered references: 'text [1]' in the body and a '## References' list."""
    refs: dict[str, int] = {}

    def num(m):
        url = m.group(2)
        n = refs.setdefault(url, len(refs) + 1)
        return f"{m.group(1)} [{n}]"
    body = re.sub(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)\)", num, markdown)
    return body, "\n".join(f"[{n}]: {u}" for u, n in refs.items())
