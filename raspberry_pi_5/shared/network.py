from __future__ import annotations

import socket
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse


@dataclass(frozen=True, slots=True)
class ControlEndpoint:
    scheme: str
    host: str
    port: int

    @property
    def uri(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


def parse_control_endpoint(raw_value: str, default_port: int) -> ControlEndpoint:
    value = raw_value.strip()
    if not value:
        raise ValueError("Enter the Streamer PC address.")

    candidate = value if "://" in value else f"ws://{value}"

    try:
        parsed = urlparse(candidate)
        port = parsed.port or default_port
    except ValueError as exc:
        raise ValueError(
            "Invalid address. Use an IP like 192.168.1.20, "
            "192.168.1.20:8765, or ws://192.168.1.20:8765."
        ) from exc

    host = parsed.hostname
    if not host:
        raise ValueError("Invalid address. Enter the Streamer PC LAN IP.")

    if host in {"0.0.0.0", "::"}:
        raise ValueError(
            "0.0.0.0 is only a streamer listen/bind address. "
            "Connect to the Streamer PC LAN IP, such as 192.168.x.x or 10.x.x.x."
        )

    if not (1 <= port <= 65535):
        raise ValueError("Port must be between 1 and 65535.")

    scheme = parsed.scheme.lower()
    if scheme == "http":
        scheme = "ws"
    elif scheme == "https":
        scheme = "wss"
    elif scheme not in {"ws", "wss"}:
        raise ValueError("Use ws:// or wss:// for the control address.")

    return ControlEndpoint(scheme=scheme, host=host, port=port)


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(("8.8.8.8", 80))
            addresses.add(probe.getsockname()[0])
        except OSError:
            pass

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            addresses.add(address)
    except OSError:
        pass

    lan_addresses: list[str] = []
    for address in sorted(addresses):
        parsed = ip_address(address)
        if parsed.is_loopback or parsed.is_link_local:
            continue
        if parsed.is_private:
            lan_addresses.append(address)

    return lan_addresses


def local_access_hint(port: int) -> str:
    addresses = local_ipv4_addresses()
    if not addresses:
        return f"No LAN IPv4 detected. Same-machine test: 127.0.0.1:{port}"

    return ", ".join(f"{address}:{port}" for address in addresses)
