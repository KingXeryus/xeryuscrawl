"""The home-network rule: only http and https web addresses on the public internet. Refused: localhost and .local/.internal
names, private, loopback, link-local, reserved, multicast and carrier-grade NAT (100.64.0.0/10, used by mesh VPNs)
addresses, and IPv4 addresses written as IPv6, checked on every address a name resolves to."""
import ipaddress
import socket
from urllib.parse import urlparse


class BrowserError(Exception):
    pass


def check_url(url: str, resolve=socket.getaddrinfo) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise BrowserError("only http and https web pages")
    host = u.hostname.lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local") or host.endswith(".internal"):
        raise BrowserError("local addresses are off limits")
    try:
        addrs = {ipaddress.ip_address(a[4][0]) for a in resolve(host, None)}
    except (socket.gaierror, ValueError) as exc:
        raise BrowserError(f"can't find that website ({exc})")
    for ip in addrs:
        ip = getattr(ip, "ipv4_mapped", None) or ip  # ::ffff:127.0.0.1 is 127.0.0.1
        # not is_global also covers 100.64.0.0/10, which is_private misses
        if not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise BrowserError("that address is on this PC or the home network, which is off limits")
    return url
