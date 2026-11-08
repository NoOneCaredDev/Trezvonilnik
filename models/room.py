from __future__ import annotations
from dataclasses import dataclass, field
from .user import User


@dataclass
class Room:
    room_id: str
    host_id: int
    users: dict[int, User] = field(default_factory=dict)
