from __future__ import annotations
import time
from dataclasses import dataclass, field


@dataclass
class NetworkStats:
    sent_packets: int = 0
    received_packets: int = 0
    invalid_packets: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    last_rtt_ms: float | None = None
    started_at: float = field(default_factory=time.time)
    _mark: tuple = field(default_factory=lambda: (time.monotonic(), 0, 0), repr=False)

    def on_send(self, size: int) -> None:
        self.sent_packets += 1
        self.bytes_sent += size

    def on_recv(self, size: int) -> None:
        self.received_packets += 1
        self.bytes_received += size

    def on_invalid(self) -> None:
        self.invalid_packets += 1

    @property
    def uptime(self) -> float:
        return time.time() - self.started_at

    def snapshot(self) -> dict:
        now = time.monotonic()
        t0, s0, r0 = self._mark
        dt = max(0.001, now - t0)
        up = (self.bytes_sent - s0) * 8 / 1000 / dt
        down = (self.bytes_received - r0) * 8 / 1000 / dt
        self._mark = (now, self.bytes_sent, self.bytes_received)
        return {
            "sent": self.sent_packets, "received": self.received_packets,
            "invalid": self.invalid_packets, "rtt_ms": self.last_rtt_ms,
            "uptime": self.uptime, "up_kbps": up, "down_kbps": down,
        }
