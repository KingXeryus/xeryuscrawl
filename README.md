# XeryusCrawl

A web crawler, scraper and research tool that runs on your own computer, for coding agents (Claude Code, Codex and any MCP
client) and for your own scripts.

- **Read anything**: web pages as clean Markdown, a "fit" version without menus and ads (or only what matches a question),
  HTML, links (internal and external), images, video, audio, tables, numbered citations, ranked chunks, a summary, the
  page's branding (colours, fonts, logo), a screenshot or a PDF; PDF, Word, Excel and PowerPoint files; XML, JSON, CSV and
  Markdown documents. Metadata includes structured data (JSON-LD, microdata, OpenGraph), the canonical address and icons.
- **JavaScript pages** open in a headless browser automatically: page actions (click, type, scroll, press, your own
  JavaScript, wait for an element, screenshots and snapshots between steps), full-page scrolling for infinite scroll and lazy
  images, sessions that keep cookies, phone emulation, language and region.
- **Whole sites**: map a site from its sitemaps, feeds and links; crawl it breadth-first, depth-first or best-first, several
  pages at once, with include/exclude rules, limits, a per-site delay and clean, de-duplicated addresses; resume a stopped
  crawl, or stop once a question is covered; read thousands of pages in a batch; webhooks for job progress; change tracking
  (new, same or changed since the last visit, with a diff).
- **Pull out data** with CSS or XPath schemas and ready-made patterns (emails, phones, prices, dates and more), or with an AI
  model: answer a question from pages or a whole site (`https://example.com/*`), fill a JSON schema, let an agent browse
  toward a goal, write a reusable schema, or write a scraping script.
- **Search and deep research**: web, news and image search with time filters; deep research searches a question from
  several angles, reads the results, follows the best links, searches again for what is still thin, and returns numbered
  sources with the passages that answer it.

Crawling, scraping, search and deep research need no AI model. Answers, AI extraction, summaries and the agent use the model
you choose: a local one (Ollama, LM Studio, llama.cpp) or a cloud provider with your own API key (OpenAI, Anthropic, Google
Gemini, OpenRouter, Groq, DeepSeek).

## Safety

- Addresses on your computer or your network (private, loopback, link-local, carrier-grade NAT, IPv4-in-IPv6) are refused
  on every redirect, on the address actually connected to, and on every request a page's own scripts make.
- robots.txt and a polite per-site pace are on by default; busy sites are retried with back-off. Pages behind logins,
  captchas or paywalls come back as blocked.
- Page text is always returned as untrusted data and never acted on. Scripts it writes are never run.
- Stealth mode exists but is off unless asked for. No proxies, no saved logins. Your API keys stay in your own settings file.

## Install

Python 3.11 or newer and [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/KingXeryus/xeryuscrawl
xeryuscrawl install-browser
xeryuscrawl setup
```

`setup` asks which AI model to use (none, local, or a cloud provider with your own key) and which search engine:

- **SearXNG** (free, on your computer): `xeryuscrawl install-search` sets it up with Docker if you have it, or downloads it from
  [SearXNG's own repository](https://github.com/searxng/searxng) on Linux and macOS (then `xeryuscrawl start-search`).
- **Brave Search** with your own API key: no install.

`xeryuscrawl status` shows the settings (keys hidden) and checks search and the model work.

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

Tools: `scrape`, `map_site`, `crawl`, `crawl_status`, `batch_scrape`, `extract`, `search`, `ask`, `agent`, `deep_research`.

To have searches, look-ups, page reading and research always use it, copy `skills/xeryuscrawl` into `~/.claude/skills/`
(Claude Code) or `~/.codex/skills/` (Codex).

## Settings

`xeryuscrawl setup` writes `~/.xeryuscrawl/config.json`; environment variables of the same names override it:

| Variable | Default | What |
| --- | --- | --- |
| `XERYUSCRAWL_HOME` | `~/.xeryuscrawl` | settings, cache, jobs, sessions and the files folder |
| `XERYUSCRAWL_LLM_PROVIDER` | `local` | `local`, `openai`, `anthropic`, `gemini`, `openrouter`, `groq` or `deepseek` |
| `XERYUSCRAWL_LLM_KEY` | | your API key for a cloud provider |
| `XERYUSCRAWL_LLM_MODEL` | per provider | the model's name |
| `XERYUSCRAWL_LLM_URL` | per provider | the server's address (local: `http://127.0.0.1:11434`) |
| `XERYUSCRAWL_SEARCH` | `searxng` | `searxng` or `brave` |
| `XERYUSCRAWL_SEARXNG` | `http://127.0.0.1:8888` | your SearXNG |
| `XERYUSCRAWL_BRAVE_KEY` | | your Brave Search API key |
| `XERYUSCRAWL_VOICE` | off | text-to-speech service for spoken answers |
| `XERYUSCRAWL_PORT` | `18102` | port of the optional REST service |
| `XERYUSCRAWL_USER_AGENT` | `XeryusCrawl/0.2 (...)` | how it names itself to websites |

## REST service (optional)

`xeryuscrawl serve` starts a REST service on 127.0.0.1 that only this computer can call, with a secret written to
`<home>/crawl.secret` (header `X-Crawl-Secret`): `/v2/scrape`, `/v2/map`, `/v2/crawl`, `/v2/batch/scrape` (with `GET` status,
`DELETE` to stop and `/resume`), `/v2/search`, `/v2/extract`, `/v2/agent`, `/v2/ask`, `/v2/search-answer`, `/v2/speak`,
`/v2/script`, `/v2/schema`, `/v2/research`, `/v2/subdomains`. Option names are accepted in snake_case or camelCase.

## Tests

```bash
uv run --with pytest pytest tests
```

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE.md): free for any noncommercial use. Commercial use needs a separate licence.
