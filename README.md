# XeryusCrawl

A web crawler and deep-research tool that runs on your own computer, for coding agents (Claude Code, Codex and any MCP
client) and for your own scripts.

- **Read a page** as clean Markdown, a "fit" version without menus and ads (or only what matches a question), HTML, links
  (internal and external), images, video, audio, tables, numbered citations, ranked chunks, a screenshot or a PDF.
- **JavaScript pages** open in a headless browser automatically: page actions (click, type, scroll, press), your own
  JavaScript, waiting for an element, full-page scrolling for infinite scroll and lazy images, sessions that keep cookies.
- **Whole sites**: map a site (sitemaps and links), crawl it breadth-first, depth-first or best-first with include/exclude
  rules and limits, resume a stopped crawl, or stop once a question is covered; read thousands of pages in a batch.
- **Pull out data** with CSS or XPath schemas and ready-made patterns (emails, phones, prices, dates and more), or with a
  local AI model: answer a question from pages, fill a JSON schema, write a reusable schema, or write a scraping script.
- **Deep research**: searches a question from several angles, reads the results, follows the best links, searches again for
  what is still thin, and returns numbered sources with the passages that answer it, ready for an agent to write a report.
- **Documents**: XML, JSON, CSV, Markdown and text, from the web or from its own files folder.

## Safety

- Addresses on your computer or your network (private, loopback, link-local, carrier-grade NAT, IPv4-in-IPv6) are refused
  on every redirect, on the address actually connected to, and on every request a page's own scripts make.
- robots.txt and a polite per-site pace are on by default. Pages behind logins, captchas or paywalls come back as blocked.
- Page text is always returned as untrusted data and never acted on. Scripts it writes are never run.
- Stealth mode exists but is off unless asked for. No proxies, no saved logins.

## Install

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/KingXeryus/xeryuscrawl
playwright install chromium
```

Web search and deep research need a [SearXNG](https://docs.searxng.org/) instance with its JSON output turned on, for
example in Docker on port 8888. AI extraction needs a local OpenAI-compatible model server (Ollama by default).

## Use it from Claude Code

```bash
claude mcp add --scope user xeryuscrawl -- xeryuscrawl-mcp
```

## Use it from Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.xeryuscrawl]
command = "xeryuscrawl-mcp"
tool_timeout_sec = 900
```

Tools: `scrape`, `map_site`, `crawl`, `crawl_status`, `extract`, `search`, `ask`, `deep_research`.

To have "deep research" always use it, copy `skills/xeryuscrawl-deep-research` into `~/.claude/skills/` (Claude Code) or
`~/.codex/skills/` (Codex).

## Settings

All optional environment variables:

| Variable | Default | What |
| --- | --- | --- |
| `XERYUSCRAWL_HOME` | `~/.xeryuscrawl` | cache, jobs, sessions and the files folder |
| `XERYUSCRAWL_SEARXNG` | `http://127.0.0.1:8888` | SearXNG for web search |
| `XERYUSCRAWL_LLM_URL` | `http://127.0.0.1:11434` | local OpenAI-compatible model server |
| `XERYUSCRAWL_LLM_MODEL` | `qwen3:8b` | model name there |
| `XERYUSCRAWL_VOICE` | off | text-to-speech service for spoken answers |
| `XERYUSCRAWL_PORT` | `18102` | port of the optional REST service |
| `XERYUSCRAWL_USER_AGENT` | `XeryusCrawl/0.1 (...)` | how it names itself to websites |

## REST service (optional)

`xeryuscrawl` starts a REST service on 127.0.0.1 that only this computer can call, with a secret written to
`<home>/crawl.secret` (header `X-Crawl-Secret`): `/v2/scrape`, `/v2/map`, `/v2/crawl`, `/v2/batch/scrape`, `/v2/search`,
`/v2/extract`, `/v2/ask`, `/v2/search-answer`, `/v2/speak`, `/v2/script`, `/v2/schema`, `/v2/research`, `/v2/subdomains`.

## Tests

```bash
uv run --with pytest pytest tests
```

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE.md): free for any noncommercial use. Commercial use needs a separate licence.
