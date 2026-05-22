"""Collector for network interfaces, routes, DNS, sockets, and firewall state."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import psutil

from kinatio.collectors.base import Collector
from kinatio.config import AppConfig
from kinatio.domain.models import (
    AvailabilityInfo,
    ConnectionEntry,
    DnsConfig,
    NetworkAddress,
    NetworkInterface,
    NetworkState,
    PortEntry,
    RouteEntry,
    utc_now,
)
from kinatio.execution.backends import detect_firewall_backend, read_firewall_status
from kinatio.execution.subprocess import SafeSubprocessRunner


class NetworkCollector(Collector):
    name = "network"
    subsystem = "network"
    interval = 6.0

    def __init__(self) -> None:
        self._firewall_backend: str | None = None
        self._firewall_backend_resolved = False

    async def collect(self, runner: SafeSubprocessRunner, config: AppConfig) -> NetworkState:
        interfaces = self._collect_interfaces()
        routes = await self._collect_routes(runner)
        dns = self._collect_dns()
        listening_ports, connections = self._collect_connections()
        firewall_backend = self._resolve_firewall_backend(config)
        firewall = await read_firewall_status(runner, firewall_backend)
        return NetworkState(
            refreshed_at=utc_now(),
            interfaces=interfaces,
            routes=routes,
            dns=dns,
            listening_ports=listening_ports,
            active_connections=connections,
            firewall=firewall,
            availability=AvailabilityInfo(available=True),
        )

    def _resolve_firewall_backend(self, config: AppConfig) -> str | None:
        if not self._firewall_backend_resolved:
            self._firewall_backend = detect_firewall_backend(config.firewall_backend_precedence)
            self._firewall_backend_resolved = True
        return self._firewall_backend

    def _collect_interfaces(self) -> list[NetworkInterface]:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io_counters = psutil.net_io_counters(pernic=True)
        interfaces: list[NetworkInterface] = []
        for name, addresses in addrs.items():
            stat = stats.get(name)
            io = io_counters.get(name)
            mac_address = None
            normalized: list[NetworkAddress] = []
            for address in addresses:
                if getattr(socket, "AF_PACKET", object()) == address.family:
                    mac_address = address.address
                    continue
                if address.family == socket.AF_INET:
                    family = "ipv4"
                elif address.family == socket.AF_INET6:
                    family = "ipv6"
                else:
                    family = str(address.family)
                normalized.append(
                    NetworkAddress(
                        family=family,
                        address=address.address,
                        netmask=address.netmask,
                        broadcast=address.broadcast,
                    )
                )
            interfaces.append(
                NetworkInterface(
                    name=name,
                    is_up=bool(stat.isup) if stat else False,
                    speed_mbps=stat.speed if stat else None,
                    mtu=stat.mtu if stat else None,
                    mac_address=mac_address,
                    addresses=normalized,
                    rx_bytes=io.bytes_recv if io else 0,
                    tx_bytes=io.bytes_sent if io else 0,
                )
            )
        interfaces.sort(key=lambda interface: interface.name)
        return interfaces

    async def _collect_routes(self, runner: SafeSubprocessRunner) -> list[RouteEntry]:
        result = await runner.run(["ip", "-j", "route", "show"], timeout=5.0, allow_missing=True)
        if result.missing_dependency or result.returncode != 0:
            return []
        raw_routes = json.loads(result.stdout or "[]")
        routes: list[RouteEntry] = []
        for route in raw_routes:
            routes.append(
                RouteEntry(
                    destination=route.get("dst", "default"),
                    gateway=route.get("gateway"),
                    device=route.get("dev"),
                    protocol=route.get("protocol"),
                    metric=route.get("metric"),
                    scope=route.get("scope"),
                )
            )
        return routes

    def _collect_dns(self) -> DnsConfig:
        resolv_conf = Path("/etc/resolv.conf")
        servers: list[str] = []
        search: list[str] = []
        if resolv_conf.exists():
            for line in resolv_conf.read_text(encoding="utf-8", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if stripped.startswith("nameserver "):
                    servers.append(stripped.split(maxsplit=1)[1])
                elif stripped.startswith("search "):
                    search.extend(stripped.split()[1:])
        return DnsConfig(servers=servers, search=search, source=str(resolv_conf))

    def _collect_connections(self) -> tuple[list[PortEntry], list[ConnectionEntry]]:
        listening_ports: list[PortEntry] = []
        connections: list[ConnectionEntry] = []
        for connection in psutil.net_connections(kind="inet"):
            local_address = connection.laddr.ip if connection.laddr else "0.0.0.0"
            local_port = connection.laddr.port if connection.laddr else 0
            remote_address = connection.raddr.ip if connection.raddr else None
            remote_port = connection.raddr.port if connection.raddr else None
            protocol = "tcp" if connection.type == socket.SOCK_STREAM else "udp"
            if connection.status == psutil.CONN_LISTEN:
                process_name = None
                if connection.pid:
                    try:
                        process_name = psutil.Process(connection.pid).name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        process_name = None
                listening_ports.append(
                    PortEntry(
                        protocol=protocol,
                        local_address=local_address,
                        local_port=local_port,
                        pid=connection.pid,
                        process_name=process_name,
                    )
                )
            connections.append(
                ConnectionEntry(
                    protocol=protocol,
                    status=connection.status,
                    local_address=local_address,
                    local_port=local_port,
                    remote_address=remote_address,
                    remote_port=remote_port,
                    pid=connection.pid,
                )
            )
        listening_ports.sort(key=lambda item: (item.local_port, item.protocol))
        connections = connections[:200]
        return listening_ports, connections
