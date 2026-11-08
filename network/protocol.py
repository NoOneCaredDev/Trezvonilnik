from __future__ import annotations
import hashlib
import hmac
import json
import struct
from enum import IntEnum
from dataclasses import dataclass

MAGIC = b"TRZ1"
VERSION = 2
# magic, version, type, sender_id, seq, payload length
HEADER = struct.Struct("!4sBBIQI")
MAC_SIZE = 16
MAX_DATAGRAM = 60_000

# Видео и аватарки не влезают в один безопасный датаграм → режем на куски.
FRAG = struct.Struct("!IHH")        # id сообщения, номер куска, всего кусков
FRAG_CHUNK = 1100                    # + заголовки + MAC ≈ 1.2 КБ, меньше любого MTU


class PacketType(IntEnum):
    HELLO = 1
    WELCOME = 2
    HEARTBEAT = 3
    USER_LIST = 4
    AUDIO = 5        # голос
    VIDEO = 6        # фрагмент JPEG-кадра
    KICK = 7
    ERROR = 8
    CONTROL = 9      # JSON-команды (состояние, админка, реакции, колесо, музыка…)
    SFX = 10         # звуки саундпада (отдельный канал, чтобы их можно было глушить)
    MUSIC = 11       # звук музыкального бота (только от хоста)
    BLOB = 12        # фрагмент аватарки
    PONG = 13


@dataclass(frozen=True)
class Packet:
    kind: PacketType
    sender_id: int
    sequence: int
    payload: bytes


def encode(packet: Packet, password: str) -> bytes:
    header = HEADER.pack(MAGIC, VERSION, int(packet.kind), packet.sender_id,
                         packet.sequence, len(packet.payload))
    body = header + packet.payload
    mac = hmac.new(password.encode("utf-8"), body, hashlib.sha256).digest()[:MAC_SIZE]
    return body + mac


def decode(data: bytes, password: str) -> Packet:
    if len(data) < HEADER.size + MAC_SIZE or len(data) > MAX_DATAGRAM:
        raise ValueError("Invalid packet size")
    magic, version, kind, sender, seq, length = HEADER.unpack(data[:HEADER.size])
    if magic != MAGIC or version != VERSION:
        raise ValueError("Unsupported protocol")
    if length != len(data) - HEADER.size - MAC_SIZE:
        raise ValueError("Payload length mismatch")
    body, received_mac = data[:-MAC_SIZE], data[-MAC_SIZE:]
    expected = hmac.new(password.encode("utf-8"), body, hashlib.sha256).digest()[:MAC_SIZE]
    if not hmac.compare_digest(received_mac, expected):
        raise ValueError("Invalid packet authentication")
    try:
        packet_type = PacketType(kind)
    except ValueError as exc:
        raise ValueError("Unknown packet type") from exc
    return Packet(packet_type, sender, seq, data[HEADER.size:-MAC_SIZE])


def pack_json(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def unpack_json(data: bytes):
    return json.loads(data.decode("utf-8"))


def split_fragments(msg_id: int, data: bytes, chunk: int = FRAG_CHUNK) -> list[bytes]:
    count = max(1, -(-len(data) // chunk))
    if count > 0xFFFF:
        raise ValueError("Message too large")
    return [FRAG.pack(msg_id & 0xFFFFFFFF, i, count) + data[i * chunk:(i + 1) * chunk]
            for i in range(count)]


def parse_fragment(payload: bytes) -> tuple[int, int, int, bytes]:
    if len(payload) < FRAG.size:
        raise ValueError("Short fragment")
    msg_id, index, count = FRAG.unpack(payload[:FRAG.size])
    if count == 0 or index >= count:
        raise ValueError("Bad fragment header")
    return msg_id, index, count, payload[FRAG.size:]
