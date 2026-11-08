from __future__ import annotations
import time
from network.protocol import parse_fragment


class FragmentReassembler:
    """Собирает сообщения из кусков.

    latest_only=True (видео): кадр старше уже собранного отбрасывается, а недособранные
    старые кадры выкидываются — лучше пропустить кадр, чем показывать его с опозданием.
    """

    def __init__(self, ttl: float = 1.5, max_pending: int = 4, latest_only: bool = False):
        self.ttl = ttl
        self.max_pending = max_pending
        self.latest_only = latest_only
        self._pending: dict[tuple, dict] = {}
        self._last_done: dict[int, int] = {}

    def feed(self, key: int, payload: bytes, now: float | None = None) -> bytes | None:
        now = time.monotonic() if now is None else now
        msg_id, index, count, chunk = parse_fragment(payload)
        if self.latest_only:
            last = self._last_done.get(key)
            if last is not None and 0 < ((last - msg_id) & 0xFFFFFFFF) < 0x80000000:
                return None                        # пришёл кадр старше уже показанного
        self._expire(now)
        slot = self._pending.get((key, msg_id))
        if slot is None:
            own = [k for k in self._pending if k[0] == key]
            while len(own) >= self.max_pending:
                oldest = min(own, key=lambda k: self._pending[k]["t"])
                self._pending.pop(oldest, None)
                own.remove(oldest)
            slot = self._pending[(key, msg_id)] = {"count": count, "parts": {}, "t": now}
        if slot["count"] != count:
            self._pending.pop((key, msg_id), None)
            return None
        slot["parts"][index] = chunk
        if len(slot["parts"]) < count:
            return None
        self._pending.pop((key, msg_id), None)
        if self.latest_only:
            self._last_done[key] = msg_id
            for k in [k for k in self._pending if k[0] == key]:
                if 0 < ((msg_id - k[1]) & 0xFFFFFFFF) < 0x80000000:
                    self._pending.pop(k, None)
        return b"".join(slot["parts"][i] for i in range(count))

    def forget(self, key: int) -> None:
        self._last_done.pop(key, None)
        for k in [k for k in self._pending if k[0] == key]:
            self._pending.pop(k, None)

    def _expire(self, now: float) -> None:
        for k in [k for k, v in self._pending.items() if now - v["t"] > self.ttl]:
            self._pending.pop(k, None)
