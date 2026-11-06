"""HTML to Markdown with Python's own HTML parser: a forgiving tree that closes tags the way browsers do, the main content
(article or main, else the body without menus, headers, footers, forms and ads), links, media, tables and page details."""
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DROP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object", "head"}
CHROME = {"nav", "header", "footer", "aside", "form", "button", "select", "dialog"}
CHROME_HINT = re.compile(r"(^|[\s_-])(nav|menu|footer|header|sidebar|cookie|banner|advert|ad|ads|promo|share|social|breadcrumb|related|comments?|newsletter|popup|modal)([\s_-]|$)", re.I)
BLOCK = {"p", "div", "section", "article", "main", "ul", "ol", "li", "table", "tr", "blockquote", "pre", "figure", "figcaption",
         "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt", "dd", "hr", "br"}
# closing these implicitly when a sibling opens, as browsers do
AUTOCLOSE = {"p": BLOCK - {"br"} | {"p"}, "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr"}, "td": {"td", "th", "tr"}, "th": {"td", "th", "tr"}, "option": {"option"}}


class Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.kids, self.parent = tag, dict(attrs or {}), [], parent

    def text(self) -> str:
        return "".join(k if isinstance(k, str) else ("" if k.tag in DROP else k.text()) for k in self.kids)

    def find_all(self, tag):
        for k in self.kids:
            if isinstance(k, Node):
                if k.tag == tag:
                    yield k
                yield from k.find_all(tag)


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        for closes, opener in ((t, s) for t, s in AUTOCLOSE.items() if tag in s):
            n = self.cur
            while n is not self.root and n.tag not in ("table", "ul", "ol", "dl", "body", "div"):
                if n.tag == closes:
                    self.cur = n.parent
                    break
                n = n.parent
        if tag == "body":  # an unclosed <head> ends where the body starts
            n = self.cur
            while n is not self.root and n.tag != "head":
                n = n.parent
            if n is not self.root:
                self.cur = n.parent
        node = Node(tag, [(k, v or "") for k, v in attrs], self.cur)
        self.cur.kids.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(Node(tag, [(k, v or "") for k, v in attrs], self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:
            n = n.parent
        if n is not self.root:  # a stray closing tag is ignored, as browsers do
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def parse(html: str) -> Node:
    t = Tree()
    t.feed(html)
    t.close()
    return t.root


def _is_chrome(n: Node) -> bool:
    if n.tag in CHROME or n.attrs.get("role") in ("navigation", "banner", "contentinfo", "complementary", "search") or n.attrs.get("aria-hidden") == "true":
        return True
    hint = f"{n.attrs.get('class', '')} {n.attrs.get('id', '')}"
    return bool(CHROME_HINT.search(hint)) and n.tag not in ("article", "main", "body")


def main_node(root: Node) -> Node:
    """The page's main content: <main> or the <article> with the most text, else <body>."""
    for tag in ("main", "article"):
        found = sorted(root.find_all(tag), key=lambda n: len(n.text()), reverse=True)
        if found and len(found[0].text().strip()) > 200:
            return found[0]
    return next(root.find_all("body"), root)


def _inline(s: str) -> str:
    return re.sub(r"[ \t\r\n\f]+", " ", s)


class Writer:
    def __init__(self, base: str, only_main: bool):
        self.base, self.only_main, self.out, self.links = base, only_main, [], []

    def walk(self, n, depth=0):
        for k in n.kids:
            if isinstance(k, str):
                self.out.append(_inline(k))
                continue
            t = k.tag
            if t in DROP or self.only_main and _is_chrome(k) or t in ("input", "option"):
                continue
            if t in ("h1", "h2", "h3", "h4", "h5", "h6"):
                # an unclosed heading swallows what follows: its title is the text before the first block; the rest is walked as usual
                cut = next((i for i, c in enumerate(k.kids) if isinstance(c, Node) and c.tag in BLOCK), len(k.kids))
                txt = _inline("".join(c if isinstance(c, str) else c.text() for c in k.kids[:cut])).strip()
                if txt:
                    self.out.append(f"\n\n{'#' * int(t[1])} {txt}\n\n")
                if cut < len(k.kids):
                    rest = Node("div", None, k)
                    rest.kids = k.kids[cut:]
                    self.walk(rest, depth)
            elif t == "p":
                self.out.append("\n\n"); self.walk(k, depth); self.out.append("\n\n")
            elif t == "br":
                self.out.append("  \n")
            elif t == "hr":
                self.out.append("\n\n---\n\n")
            elif t in ("strong", "b"):
                txt = _inline(k.text()).strip()
                self.out.append(f"**{txt}**" if txt else "")
            elif t in ("em", "i"):
                txt = _inline(k.text()).strip()
                self.out.append(f"*{txt}*" if txt else "")
            elif t == "code" and (k.parent is None or k.parent.tag != "pre"):
                self.out.append(f"`{k.text().strip()}`")
            elif t == "pre":
                self.out.append(f"\n\n```\n{k.text().strip(chr(10))}\n```\n\n")
            elif t == "a":
                href = k.attrs.get("href", "").strip()
                txt = _inline(k.text()).strip()
                if href and not href.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
                    url = urldefrag(urljoin(self.base, href))[0]
                    self.links.append(url)
                    self.out.append(f"[{txt}]({url})" if txt else "")
                else:
                    self.out.append(txt)
            elif t == "img":
                src = k.attrs.get("src", "").strip()
                if src and not src.startswith("data:"):
                    self.out.append(f"![{_inline(k.attrs.get('alt', '')).strip()}]({urljoin(self.base, src)})")
            elif t in ("ul", "ol"):
                self.out.append("\n\n")
                for i, li in enumerate((c for c in k.kids if isinstance(c, Node) and c.tag == "li"), 1):
                    sub = Writer(self.base, self.only_main)
                    sub.walk(li, depth + 1)
                    self.links += sub.links
                    body = re.sub(r"\n{2,}", "\n", "".join(sub.out)).strip().replace("\n", "\n" + "  " * (depth + 1))
                    self.out.append(f"{'  ' * depth}{f'{i}.' if t == 'ol' else '-'} {body}\n")
                self.out.append("\n")
            elif t == "blockquote":
                sub = Writer(self.base, self.only_main)
                sub.walk(k, depth)
                self.links += sub.links
                self.out.append("\n\n" + "\n".join("> " + ln for ln in tidy("".join(sub.out)).splitlines()) + "\n\n")
            elif t == "table":
                self.out.append(self._table(k))
            elif t in BLOCK:
                self.out.append("\n"); self.walk(k, depth); self.out.append("\n")
            else:
                self.walk(k, depth)

    def _table(self, t: Node) -> str:
        rows = []
        for tr in t.find_all("tr"):
            cells = [_inline(c.text()).strip().replace("|", "\\|") for c in tr.kids if isinstance(c, Node) and c.tag in ("td", "th")]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width] + ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n\n" + "\n".join(lines) + "\n\n"


def tidy(md: str) -> str:
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n[ \t]+(?=[^\s\-\d*>|])", "\n", md)
    md = re.sub(r"(?<=\S) {2,}", " ", md)  # keeps list indents
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def metadata(root: Node, url: str) -> dict:
    meta = {}
    title = next(root.find_all("title"), None)
    if title:
        meta["title"] = _inline(title.text()).strip()
    for m in root.find_all("meta"):
        key = m.attrs.get("name") or m.attrs.get("property")
        if key and m.attrs.get("content") and (key in ("description", "keywords", "author", "robots") or key.startswith(("og:", "twitter:"))):
            meta[key] = m.attrs["content"].strip()
    html = next(root.find_all("html"), None)
    if html and html.attrs.get("lang"):
        meta["language"] = html.attrs["lang"]
    meta.setdefault("title", meta.get("og:title", ""))
    meta["sourceURL"] = url
    return meta


def convert(html: str, url: str, only_main: bool = True) -> dict:
    root = parse(html)
    w = Writer(url, only_main)
    w.walk(main_node(root) if only_main else next(root.find_all("body"), root))
    all_links = Writer(url, False)
    all_links.walk(root)
    seen = list(dict.fromkeys(all_links.links))
    return {"markdown": unescape(tidy("".join(w.out))), "links": seen, "metadata": metadata(root, url)}


def media(root: Node, url: str) -> dict:
    """Images (with srcset sizes and a usefulness score: big, described, in the content scores higher), videos, audio and
    frames."""
    def abs_(u):
        return urljoin(url, u.strip()) if u and not u.strip().startswith("data:") else None
    images = []
    for im in root.find_all("img"):
        src = abs_(im.attrs.get("src") or im.attrs.get("data-src") or "")
        if not src:
            continue
        alt = _inline(im.attrs.get("alt", "")).strip()
        w = int(re.sub(r"\D", "", im.attrs.get("width", "")) or 0)
        score = (2 if alt else 0) + (2 if w >= 300 else 1 if w >= 100 else 0) + (0 if re.search(r"logo|icon|sprite|pixel|avatar", src, re.I) else 1)
        srcset = [abs_(p.split()[0]) for p in im.attrs.get("srcset", "").split(",") if p.strip()]
        images.append({"src": src, "alt": alt, "width": w or None, "srcset": [s for s in srcset if s], "score": score})
    def group(tag):
        out = []
        for n in root.find_all(tag):
            src = abs_(n.attrs.get("src", "")) or next((abs_(s.attrs.get("src", "")) for s in n.find_all("source") if s.attrs.get("src")), None)
            if src:
                out.append({"src": src, "type": n.attrs.get("type") or next((s.attrs.get("type") for s in n.find_all("source")), None)})
        return out
    frames = [{"src": s} for f in root.find_all("iframe") if (s := abs_(f.attrs.get("src", "")))]
    return {"images": sorted(images, key=lambda i: -i["score"]), "videos": group("video"), "audios": group("audio"), "iframes": frames}


def tables(root: Node) -> list[dict]:
    """Each data table as headers and rows (layout tables with one column are skipped)."""
    out = []
    for t in root.find_all("table"):
        rows = [[_inline(c.text()).strip() for c in tr.kids if isinstance(c, Node) and c.tag in ("td", "th")] for tr in t.find_all("tr")]
        rows = [r for r in rows if any(r)]
        if not rows or max(map(len, rows)) < 2:
            continue
        first = next(t.find_all("tr"))
        has_head = any(isinstance(c, Node) and c.tag == "th" for c in first.kids)
        cap = next(t.find_all("caption"), None)
        out.append({"caption": _inline(cap.text()).strip() if cap else None, "headers": rows[0] if has_head else [], "rows": rows[1:] if has_head else rows})
    return out


def split_links(links: list[str], url: str) -> dict:
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    base = host.removeprefix("www.")
    inside = [u for u in links if (h := (urlparse(u).hostname or "").removeprefix("www.")) == base or h.endswith("." + base)]
    return {"internal": inside, "external": [u for u in links if u not in inside]}
