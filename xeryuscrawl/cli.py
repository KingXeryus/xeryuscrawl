"""The xeryuscrawl command.

  xeryuscrawl setup            choose the AI model (none, a local server, or a cloud provider with your own API key) and the
                               search engine (SearXNG, or Brave Search with your own key); saved to <home>/config.json
  xeryuscrawl install-search   set up SearXNG on this computer: with Docker if it's there, else from SearXNG's own git
                               repository into <home>/searxng (Linux and macOS)
  xeryuscrawl start-search     start the SearXNG installed from git
  xeryuscrawl install-browser  download Playwright's Chromium (for JavaScript pages, screenshots and PDFs)
  xeryuscrawl sharing on|off   share the public web passages your research finds with myMAK.ai (off unless you say yes)
  xeryuscrawl status           show the settings (keys hidden) and check search and the model work
  xeryuscrawl serve            the REST service on 127.0.0.1 (also: xeryuscrawl with no command)
Every question in setup can be given as a flag instead (see xeryuscrawl setup --help)."""
import argparse
import getpass
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

SEARXNG_GIT = "https://github.com/searxng/searxng"
SEARXNG_IMAGE = "docker.io/searxng/searxng:latest"
CONTAINER = "xeryuscrawl-searxng"
SEARCH_PORT = 8888
SHARE_QUESTION = """
Help improve myMAK.ai's AI models? If yes, the public web passages your research finds (with their web addresses) are
shared with myMAK.ai. Never your questions, searches, answers, keys or files. Details: TERMS.md. You can change this any
time: xeryuscrawl sharing on|off"""


def _save(values: dict) -> None:
    config.HOME.mkdir(parents=True, exist_ok=True)
    current = json.loads(config.CONFIG_FILE.read_text(encoding="utf-8")) if config.CONFIG_FILE.is_file() else {}
    current.update({k: v for k, v in values.items() if v is not None})
    config.CONFIG_FILE.write_text(json.dumps(current, indent=1), encoding="utf-8")
    if os.name == "posix":
        config.CONFIG_FILE.chmod(0o600)  # API keys inside: readable by you only
    print(f"Saved to {config.CONFIG_FILE}")


def _ask(question: str, default: str = "", secret: bool = False) -> str:
    if not sys.stdin.isatty():
        return default
    shown = f" [{default}]" if default and not secret else ""
    try:
        value = getpass.getpass(f"{question}: ") if secret else input(f"{question}{shown}: ")
    except EOFError:  # no keyboard (a script): the default
        return default
    return value.strip() or default


def setup(a) -> int:
    provider = a.llm or _ask("AI model: none, local, " + ", ".join(p for p in config.PROVIDERS if p != "local"), "none").lower()
    values: dict = {}
    if provider != "none":
        if provider not in config.PROVIDERS:
            print(f"Unknown provider {provider!r}.")
            return 1
        values["XERYUSCRAWL_LLM_PROVIDER"] = provider
        if provider == "local":
            values["XERYUSCRAWL_LLM_URL"] = a.llm_url or _ask("Local model server", config.PROVIDERS["local"][0])
        else:
            values["XERYUSCRAWL_LLM_KEY"] = a.llm_key or _ask(f"Your {provider} API key (hidden)", secret=True)
            if not values["XERYUSCRAWL_LLM_KEY"]:
                print("No key given; the AI features stay off until you add one.")
        values["XERYUSCRAWL_LLM_MODEL"] = a.llm_model or _ask("Model", config.PROVIDERS[provider][1])
    search = a.search or _ask("Search engine: searxng or brave", "searxng").lower()
    values["XERYUSCRAWL_SEARCH"] = search
    if search == "brave":
        values["XERYUSCRAWL_BRAVE_KEY"] = a.brave_key or _ask("Your Brave Search API key (hidden)", secret=True)
    else:
        values["XERYUSCRAWL_SEARXNG"] = a.searxng or _ask("SearXNG address", f"http://127.0.0.1:{SEARCH_PORT}")
    print(SHARE_QUESTION)
    share = a.share or _ask("Share research passages? (yes/no)", "no").lower()
    values["XERYUSCRAWL_SHARE"] = "yes" if share.startswith("y") else "no"
    if values["XERYUSCRAWL_SHARE"] == "yes":
        values["XERYUSCRAWL_INSTALL_ID"] = config.INSTALL_ID or str(__import__("uuid").uuid4())
    _save(values)
    if search == "searxng" and not a.searxng and _ask("Install SearXNG on this computer now? (y/n)", "n").lower().startswith("y"):
        return install_search(a)
    return 0


def _settings_yml(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / "settings.yml"
    if not f.is_file():  # JSON results on, no rate limiter (only this computer uses it), bound to this computer
        f.write_text(f"use_default_settings: true\nserver:\n  secret_key: \"{secrets.token_hex(32)}\"\n  limiter: false\n"
                     f"  image_proxy: false\n  bind_address: \"127.0.0.1\"\n  port: {SEARCH_PORT}\n"
                     "search:\n  formats:\n    - html\n    - json\n", encoding="utf-8")


def install_search(a=None) -> int:
    folder = config.HOME / "searxng"
    if shutil.which("docker"):
        _settings_yml(folder)
        subprocess.run(["docker", "rm", "-f", CONTAINER], capture_output=True)
        r = subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "--restart", "unless-stopped", "-p", f"127.0.0.1:{SEARCH_PORT}:8080",
                            "-v", f"{folder}:/etc/searxng:rw", SEARXNG_IMAGE])
        if r.returncode == 0:
            print(f"SearXNG is running in Docker at http://127.0.0.1:{SEARCH_PORT} (it starts again with Docker).")
            _save({"XERYUSCRAWL_SEARCH": "searxng", "XERYUSCRAWL_SEARXNG": f"http://127.0.0.1:{SEARCH_PORT}"})
        return r.returncode
    if platform.system() == "Windows":
        print("SearXNG doesn't run on Windows by itself. Install Docker Desktop and run this again, or use Brave Search with\n"
              "your own key: xeryuscrawl setup --search brave --brave-key <key>")
        return 1
    if not shutil.which("git"):
        print("Install git (or Docker) first.")
        return 1
    src = config.HOME / "searxng-src"
    if not src.is_dir():
        subprocess.run(["git", "clone", "--depth", "1", SEARXNG_GIT, str(src)], check=True)
    venv = src / ".venv"
    if not venv.is_dir():
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    pip = venv / "bin" / "pip"
    subprocess.run([str(pip), "install", "-q", "-U", "pip", "setuptools", "wheel"], check=True)
    subprocess.run([str(pip), "install", "-q", "-r", str(src / "requirements.txt")], check=True)
    subprocess.run([str(pip), "install", "-q", "--no-build-isolation", "-e", str(src)], check=True)
    _settings_yml(folder)
    _save({"XERYUSCRAWL_SEARCH": "searxng", "XERYUSCRAWL_SEARXNG": f"http://127.0.0.1:{SEARCH_PORT}"})
    print("SearXNG is installed. Start it with: xeryuscrawl start-search")
    return 0


def start_search(a=None) -> int:
    src = config.HOME / "searxng-src"
    py = src / ".venv" / "bin" / "python"
    if not py.is_file():
        print("SearXNG isn't installed from git here; run xeryuscrawl install-search.")
        return 1
    env = os.environ | {"SEARXNG_SETTINGS_PATH": str(config.HOME / "searxng" / "settings.yml")}
    log = (config.HOME / "searxng" / "searxng.log").open("a")
    p = subprocess.Popen([str(py), "-m", "searx.webapp"], cwd=src, env=env, stdout=log, stderr=log, start_new_session=True)
    print(f"SearXNG started (process {p.pid}) at http://127.0.0.1:{SEARCH_PORT}")
    return 0


def sharing(a) -> int:
    if a.state in ("on", "off"):
        values = {"XERYUSCRAWL_SHARE": "yes" if a.state == "on" else "no"}
        if a.state == "on":
            values["XERYUSCRAWL_INSTALL_ID"] = config.INSTALL_ID or str(__import__("uuid").uuid4())
        _save(values)
        if a.state == "off":  # nothing waiting is sent after you say no
            box = config.HOME / "share" / "outbox.jsonl"
            box.unlink(missing_ok=True)
        print("Sharing is " + a.state + ".")
    else:
        print("Sharing is " + ("on" if config.SHARE else "off") + ".")
    return 0


def install_browser(a=None) -> int:
    return subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"]).returncode


def status(a=None) -> int:
    from .engine import local_llm
    from .smart import search
    mask = lambda k: (k[:4] + "..." + k[-2:]) if k else "(none)"  # noqa: E731
    print(f"Home:    {config.HOME}")
    print(f"Model:   {config.LLM_PROVIDER} | {config.LLM_MODEL} | {config.LLM_URL} | key {mask(config.LLM_KEY)}")
    print(f"Sharing: {'on' if config.SHARE else 'off'}")
    print(f"Search:  {config.SEARCH} | " + (f"key {mask(config.BRAVE_KEY)}" if config.SEARCH == "brave" else config.SEARXNG))
    try:
        print(f"Search check: ok ({len(search('test', 3))} results)")
    except Exception as exc:  # noqa: BLE001
        print(f"Search check: not working: {exc}")
    try:
        print("Model check: ok (" + local_llm([{"role": "user", "content": "Reply with the word ok."}])[:40].strip() + ")")
    except Exception as exc:  # noqa: BLE001
        print(f"Model check: not working: {str(exc)[:200]}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(prog="xeryuscrawl", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("setup", help="choose the AI model and search engine")
    s.add_argument("--llm", help="none, local, " + ", ".join(p for p in config.PROVIDERS if p != "local"))
    s.add_argument("--llm-key")
    s.add_argument("--llm-model")
    s.add_argument("--llm-url")
    s.add_argument("--search", choices=["searxng", "brave"])
    s.add_argument("--brave-key")
    s.add_argument("--searxng")
    s.add_argument("--share", choices=["yes", "no"], help="share research passages with myMAK.ai (see TERMS.md)")
    sh = sub.add_parser("sharing", help="turn sharing research passages on or off")
    sh.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    for name in ("install-search", "start-search", "install-browser", "status", "serve"):
        sub.add_parser(name)
    a, rest = ap.parse_known_args()
    if a.cmd in (None, "serve"):
        from .serve import main as serve
        sys.argv = [sys.argv[0], *rest]
        serve()
        return
    sys.exit({"setup": setup, "sharing": sharing, "install-search": install_search, "start-search": start_search, "install-browser": install_browser,
              "status": status}[a.cmd](a))


if __name__ == "__main__":
    main()
