"""Scans the hub's local network for reachable hamilton_venus_mcp spokes via each
candidate's cheap /ping route (see mcp_server's server.py) rather than a full MCP
initialize+call handshake, which would be far too slow to fire speculatively at
hundreds of candidate host:port pairs.

127.0.0.1 and the hub's own bound IP are always scanned across the *full* configured
port list -- the "hub and spoke on the same computer, same IP, different port" case.
Every other host in the hub's own /prefix subnet is scanned only on the first
configured port, since a spoke PC is expected to run exactly one spoke on its default
port.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
from dataclasses import dataclass

import httpx

PORTS_ENV = "HAMILTON_MCP_DISCOVER_PORTS"
PREFIX_ENV = "HAMILTON_MCP_DISCOVER_PREFIX"
TIMEOUT_ENV = "HAMILTON_MCP_DISCOVER_TIMEOUT_S"
CONCURRENCY_ENV = "HAMILTON_MCP_DISCOVER_CONCURRENCY"

DEFAULT_PORTS = "8000-8010"
DEFAULT_PREFIX = 24
DEFAULT_TIMEOUT_S = 0.75
DEFAULT_CONCURRENCY = 100

_PING_PATH = "/ping"
_EXPECTED_SERVICE = "hamilton-venus-mcp"


@dataclass(frozen=True)
class DiscoveredSpoke:
    url: str
    name: str


def parse_ports(value: str) -> list[int]:
    """"8000-8010" -> range; "8000,9000" -> list; "8000-8005,9000" -> both, mixed.
    Sorted, de-duplicated. Raises ValueError on empty/malformed input."""
    ports: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, _, end_text = part.partition("-")
            start, end = int(start_text.strip()), int(end_text.strip())
            if start > end:
                raise ValueError(f"Invalid port range {part!r}: start > end")
            ports.update(range(start, end + 1))
        else:
            ports.add(int(part))
    if not ports:
        raise ValueError(f"No ports found in {value!r}")
    return sorted(ports)


def ports_from_env() -> list[int]:
    return parse_ports(os.environ.get(PORTS_ENV, "").strip() or DEFAULT_PORTS)


def local_ip() -> str:
    """The IP this machine would use to reach the outside world, without actually
    sending any packet (UDP "connect" just picks a local endpoint via routing, no
    handshake) -- falls back to loopback if there's no route at all (offline machine)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def candidate_targets(prefix: int | None = None) -> list[tuple[str, list[int]]]:
    resolved_prefix = prefix if prefix is not None else int(os.environ.get(PREFIX_ENV, "").strip() or DEFAULT_PREFIX)
    ports = ports_from_env()
    own_ip = local_ip()

    local_hosts = {"127.0.0.1", own_ip}
    targets: list[tuple[str, list[int]]] = [(host, ports) for host in sorted(local_hosts)]

    try:
        network = ipaddress.ip_interface(f"{own_ip}/{resolved_prefix}").network
        other_hosts = [str(h) for h in network.hosts() if str(h) not in local_hosts]
    except ValueError:
        other_hosts = []

    targets.extend((host, [ports[0]]) for host in other_hosts)
    return targets


async def _probe(client: httpx.AsyncClient, host: str, port: int, timeout_s: float) -> DiscoveredSpoke | None:
    try:
        response = await client.get(f"http://{host}:{port}{_PING_PATH}", timeout=timeout_s)
        response.raise_for_status()
        body = response.json()
    except Exception:  # noqa: BLE001 - any failure (timeout, refused, bad JSON, wrong status) just means "not a spoke"
        return None
    if not isinstance(body, dict) or body.get("service") != _EXPECTED_SERVICE:
        return None
    name = str(body.get("name") or f"{host}:{port}")
    return DiscoveredSpoke(url=f"http://{host}:{port}/mcp", name=name)


async def scan(
    *,
    prefix: int | None = None,
    timeout_s: float | None = None,
    concurrency: int | None = None,
) -> list[DiscoveredSpoke]:
    resolved_timeout = timeout_s if timeout_s is not None else float(os.environ.get(TIMEOUT_ENV, "").strip() or DEFAULT_TIMEOUT_S)
    resolved_concurrency = (
        concurrency if concurrency is not None else int(os.environ.get(CONCURRENCY_ENV, "").strip() or DEFAULT_CONCURRENCY)
    )
    targets = candidate_targets(prefix)

    semaphore = asyncio.Semaphore(resolved_concurrency)

    async def bounded_probe(client: httpx.AsyncClient, host: str, port: int) -> DiscoveredSpoke | None:
        async with semaphore:
            return await _probe(client, host, port, resolved_timeout)

    async with httpx.AsyncClient() as client:
        tasks = [bounded_probe(client, host, port) for host, ports in targets for port in ports]
        results = await asyncio.gather(*tasks)

    seen_urls: set[str] = set()
    found: list[DiscoveredSpoke] = []
    for result in results:
        if result is not None and result.url not in seen_urls:
            seen_urls.add(result.url)
            found.append(result)
    return found
