"""Resolution de l'adresse de broadcast IPv4 pour la pile BACnet/IP.

bacpypes3 ne sait envoyer en broadcast que si l'IPv4DatagramServer connait
une adresse de broadcast (attribut ``broadcast_address``). Avec une adresse
d'ecoute joker (0.0.0.0) ou un port ephemere (0), aucune adresse de broadcast
n'est derivee et tout envoi vers LocalBroadcast leve RuntimeError("no broadcast").
"""

import ipaddress
import socket
import struct
from typing import Optional, Tuple

from bacpypes3.pdu import IPv4Address

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]

BACNET_PORT = 47808
LIMITED_BROADCAST = "255.255.255.255"

_SIOCGIFADDR = 0x8915
_SIOCGIFNETMASK = 0x891B


def parse_broadcast_address(value: str, default_port: int) -> Tuple[str, int]:
    """Valide "x.x.x.x[:port]" et renvoie le tuple (ip, port)."""
    parts = value.split(":")
    if len(parts) == 1:
        ip_str, port_str = parts[0], str(default_port)
    elif len(parts) == 2:
        ip_str, port_str = parts
    else:
        raise ValueError(f"adresse de broadcast invalide: {value!r}")
    ip = ipaddress.IPv4Address(ip_str)
    port = int(port_str)
    if not 0 < port <= 65535:
        raise ValueError(f"port hors limites dans {value!r}: {port}")
    return (str(ip), port)


def _primary_ipv4() -> Optional[str]:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 1))
            return sock.getsockname()[0]
    except OSError:
        return None


def _netmask_of(ip: str) -> Optional[str]:
    if fcntl is None:
        return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for _index, name in socket.if_nameindex():
                ifreq = struct.pack("256s", name.encode()[:15])
                try:
                    addr = fcntl.ioctl(sock.fileno(), _SIOCGIFADDR, ifreq)
                    if socket.inet_ntoa(addr[20:24]) != ip:
                        continue
                    mask = fcntl.ioctl(sock.fileno(), _SIOCGIFNETMASK, ifreq)
                    return socket.inet_ntoa(mask[20:24])
                except OSError:
                    continue
    except OSError:
        return None
    return None


def detect_broadcast_address(bind: IPv4Address) -> Optional[Tuple[str, int]]:
    """Adresse de broadcast (ip, port) associee a une adresse d'ecoute.

    Renvoie None sur loopback (pas de broadcast sur 127.0.0.0/8).
    """
    port = bind.addrPort or BACNET_PORT
    if bind.addrBroadcastTuple != bind.addrTuple:
        return bind.addrBroadcastTuple
    host = bind.addrTuple[0]
    if host.startswith("127."):
        return None
    ip = host if host != "0.0.0.0" else _primary_ipv4()
    if ip is None:
        return (LIMITED_BROADCAST, port)
    netmask = _netmask_of(ip)
    if netmask is None:
        return (LIMITED_BROADCAST, port)
    network = ipaddress.ip_interface(f"{ip}/{netmask}").network
    broadcast = str(network.broadcast_address)
    if broadcast == ip:
        return (LIMITED_BROADCAST, port)
    return (broadcast, port)


def apply_broadcast_address(
    app, bind_address: str, configured: Optional[str] = None
) -> Optional[Tuple[str, int]]:
    """Renseigne ``broadcast_address`` du serveur IPv4 de l'application si absent."""
    server = getattr(getattr(app, "normal", None), "server", None)
    if server is None:
        return None
    if server.broadcast_address is not None:
        return server.broadcast_address
    bind = IPv4Address(bind_address)
    if configured:
        broadcast = parse_broadcast_address(configured, bind.addrPort or BACNET_PORT)
    else:
        broadcast = detect_broadcast_address(bind)
    if broadcast is not None:
        server.broadcast_address = broadcast
    return broadcast
