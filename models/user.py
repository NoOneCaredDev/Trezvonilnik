from __future__ import annotations
from dataclasses import dataclass, field
import time


@dataclass
class User:
    user_id: int
    nickname: str
    address: tuple[str, int]
    is_host: bool = False
    joined_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    sharing: bool = False
    stream_title: str = ""
    muted: bool = False
    deafened: bool = False
    # ограничения, которые накладывает хост (их применяет сервер, а не клиент)
    mic_locked: bool = False
    sfx_locked: bool = False
    stream_locked: bool = False
    avatar_hash: str = ""

    def public(self) -> dict:
        return {
            "id": self.user_id, "nickname": self.nickname, "host": self.is_host,
            "sharing": self.sharing, "stream_title": self.stream_title,
            "muted": self.muted, "deafened": self.deafened,
            "mic_locked": self.mic_locked, "sfx_locked": self.sfx_locked,
            "stream_locked": self.stream_locked, "avatar": self.avatar_hash,
        }
