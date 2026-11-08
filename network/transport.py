from __future__ import annotations
import socket
import sys
import threading
from collections.abc import Callable


def _disable_udp_connreset(sock: socket.socket) -> None:
    """Windows: ICMP «порт недоступен» после ухода клиента приводит к ConnectionResetError
    в recvfrom(). Раньше это убивало приёмный цикл сервера — хост переставал слышать всех."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        SIO_UDP_CONNRESET = 0x9800000C
        returned = ctypes.c_ulong(0)
        flag = ctypes.c_ulong(0)
        ctypes.windll.ws2_32.WSAIoctl(
            ctypes.c_size_t(sock.fileno()), SIO_UDP_CONNRESET,
            ctypes.byref(flag), 4, None, 0, ctypes.byref(returned), None, None)
    except Exception:
        pass


class UdpTransport:
    def __init__(self, bind_host: str = "0.0.0.0", port: int = 0, exclusive: bool = False):
        """exclusive=True (сервер): второй сокет на этот порт получит OSError. Без этого SO_REUSEADDR
        для UDP позволял двум «хостам» молча сесть на один порт и делить входящие пакеты."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if exclusive:
            if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        for opt in (socket.SO_RCVBUF, socket.SO_SNDBUF):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, opt, 4 * 1024 * 1024)
            except OSError:
                pass
        try:
            self.socket.bind((bind_host, port))
        except OSError:
            self.socket.close()          # порт занят — не оставляем сокет висеть
            raise
        self.socket.settimeout(0.5)
        _disable_udp_connreset(self.socket)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def address(self):
        return self.socket.getsockname()

    def send(self, data: bytes, address: tuple[str, int]) -> None:
        try:
            self.socket.sendto(data, address)
        except OSError:
            pass

    def start(self, handler: Callable[[bytes, tuple[str, int]], None]) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def loop():
            while not self._stop.is_set():
                try:
                    data, addr = self.socket.recvfrom(65535)
                except socket.timeout:
                    continue
                except ConnectionResetError:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    continue
                try:
                    handler(data, addr)
                except Exception:
                    # Битый датаграм не должен убивать приёмный цикл.
                    continue

        self._thread = threading.Thread(target=loop, name="udp-receiver", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        try:
            self.socket.close()
        except OSError:
            pass
        if self._thread and self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
