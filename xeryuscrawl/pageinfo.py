"""More about a page: structured data (JSON-LD, microdata, OpenGraph and Twitter cards), its canonical address and icons,
its look (branding: colours, fonts, logo, theme colour), and keeping or removing chosen parts before it is converted."""
import json
import re
from collections import Counter
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lhtml

from .extract import css_to_xpath, parse

COLOR = re.compile(r"#(?:[0-9a-f]{6}|[0-9a-f]{3})\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+(?:\s*,\s*[\d.]+)?\s*\)", re.I)
FONT = re.compile(r"font-family\s*:\s*([^;}{]+)", re.I)
DULL = {"#fff", "#ffffff", "#000", "#000000", "#eee", "#eeeeee", "#ddd", "#dddddd", "#ccc", "#cccccc", "#333", "#333333", "#666", "#666666", "#999", "#999999"}


def _select(root, selectors: list[str]):
    out = []
    for s in selectors:
        try:
            out += root.xpath(css_to_xpath(s))
        except (ValueError, etree.XPathError):
            raise ValueError(f"not a selector this reader understands: {s}")
    return out


def keep_parts(html: str, include: list[str] | None = None, exclude: list[str] | None = None) -> str:
    """Only the parts matching `include` (CSS selectors), without the parts matching `exclude`."""
    if not include and not exclude:
        return html
    root = parse(html)
    for el in _select(root, exclude or []):
        if el.getparent() is not None:
            el.drop_tree()
    if include:
        kept = _select(root, include)
        head = root.find("head")
        return ("<html>" + (lhtml.tostring(head, encoding="unicode") if head is not None else "") + "<body>"
                + "".join(lhtml.tostring(e, encoding="unicode", with_tail=False) for e in kept) + "</body></html>")
    return lhtml.tostring(root, encoding="unicode")


def _microdata(el) -> dict:
    item = {"@type": el.get("itemtype", "")}
    for prop in el.xpath(".//*[@itemprop]"):
        holder = prop.getparent()
        while holder is not None and holder.get("itemscope") is None:
            holder = holder.getparent()
        if holder is not el:
            continue
        name = prop.get("itemprop")
        value = _microdata(prop) if prop.get("itemscope") is not None else (
            prop.get("content") or prop.get("href") or prop.get("src") or prop.get("datetime") or " ".join(prop.itertext()).strip())
        item[name] = item[name] + [value] if isinstance(item.get(name), list) else [item[name], value] if name in item else value
    return item


def details(html: str, url: str) -> dict:
    """{"canonical", "favicon", "alternates", "jsonLd", "microdata"} found on the page."""
    root = parse(html)
    out: dict = {}
    for link in root.xpath("//link[@rel][@href]"):
        rel = link.get("rel", "").lower().split()
        href = urljoin(url, link.get("href"))
        if "canonical" in rel:
            out["canonical"] = href
        elif "icon" in rel or "apple-touch-icon" in rel:
            out.setdefault("favicon", href)
        elif "alternate" in rel and link.get("hreflang"):
            out.setdefault("alternates", {})[link.get("hreflang")] = href
        elif "alternate" in rel and "xml" in link.get("type", ""):
            out.setdefault("feeds", []).append(href)
    ld = []
    for s in root.xpath("//script[@type='application/ld+json']"):
        try:
            data = json.loads(s.text or "")
        except ValueError:
            continue
        ld += data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
    if ld:
        out["jsonLd"] = ld[:50]
    micro = [_microdata(el) for el in root.xpath("//*[@itemscope][not(ancestor::*[@itemscope])]")[:50]]
    if micro:
        out["microdata"] = micro
    return out


def branding(html: str, url: str, stylesheets: list[str] | None = None) -> dict:
    """The page's look: theme colour, main colours and fonts (from its styles), logo, icon and social image."""
    root = parse(html)
    css = "\n".join(s.text or "" for s in root.xpath("//style")) + "\n" + "\n".join(e.get("style", "") for e in root.xpath("//*[@style]"))
    css += "\n" + "\n".join(stylesheets or [])
    colors = Counter(c.lower().replace(" ", "") for c in COLOR.findall(css))
    fonts = Counter(f.split(",")[0].strip().strip("'\"") for f in FONT.findall(css))
    logo = next((urljoin(url, i.get("src")) for i in root.xpath("//img[@src]")
                 if re.search(r"logo", " ".join([i.get("src", ""), i.get("alt", ""), i.get("class", ""), i.get("id", "")]), re.I)), None)
    meta = {m.get("name") or m.get("property"): m.get("content") for m in root.xpath("//meta[@content]")}
    info = details(html, url)
    return {"themeColor": meta.get("theme-color"), "colors": [c for c, _ in colors.most_common(12) if c not in DULL][:6],
            "fonts": [f for f, _ in fonts.most_common(6) if f and not f.startswith(("inherit", "var("))][:4], "logo": logo,
            "favicon": info.get("favicon") or urljoin(url, "/favicon.ico"), "image": meta.get("og:image"),
            "name": meta.get("og:site_name") or meta.get("application-name")}


def stylesheet_links(html: str, url: str, limit: int = 3) -> list[str]:
    return [urljoin(url, l.get("href")) for l in parse(html).xpath("//link[@href]") if "stylesheet" in (l.get("rel") or "").lower()][:limit]
