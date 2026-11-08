from __future__ import annotations
from PySide6.QtNetwork import QNetworkInterface, QAbstractSocket


def pick_radmin(addresses: list[str]) -> list[str]:
    """Radmin VPN выдаёт адреса 26.x.x.x — их показываем первыми (их и надо отдавать друзьям)."""
    radmin = [a for a in addresses if a.startswith("26.")]
    other = [a for a in addresses if not a.startswith("26.") and not a.startswith("127.") and not a.startswith("169.254.")]
    return radmin + other


def local_ipv4() -> list[str]:
    ips = []
    for addr in QNetworkInterface.allAddresses():
        if addr.protocol() == QAbstractSocket.IPv4Protocol:
            ips.append(addr.toString())
    return pick_radmin(ips)
