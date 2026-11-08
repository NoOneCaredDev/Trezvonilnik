from __future__ import annotations
import itertools
import secrets
import struct
import threading
import time

from PySide6.QtCore import QObject, Signal

from network.protocol import (Packet, PacketType, decode, encode, pack_json, unpack_json,
                              split_fragments)
from network.reassembly import FragmentReassembler
from network.transport import UdpTransport


class RoomClient(QObject):
    """Клиентская сессия.

    Сигналы Qt — только для того, что уходит в интерфейс (список людей, команды, статус).
    Медиа-пакеты идут через обычные колбэки прямо из сетевого потока: гонять 50 аудиокадров
    в секунду через очередь событий GUI незачем (и это добавляло бы задержку).
    """
    users_changed = Signal(list)
    control_received = Signal(dict)
    connected = Signal(int)
    connection_state = Signal(str)      # connecting | online | reconnecting | failed
    kicked = Signal()
    server_error = Signal(str)
    rtt_changed = Signal(float)
    avatar_received = Signal(int, bytes)
    room_named = Signal(str)

    def __init__(self, nickname: str, host_ip: str, password: str, port: int = 5000, stats=None):
        super().__init__()
        self.nickname = nickname
        self.host = (host_ip, port)
        self.password = password
        self.stats = stats
        self.transport = UdpTransport("0.0.0.0", 0)
        self.user_id = 0
        self.host_id = 0
        self.is_host = False
        self.room_name = ""
        self.online = False
        self.on_audio = None            # (uid, payload)
        self.on_sfx = None              # (uid, payload)
        self.on_music = None            # (payload)
        self.on_video = None            # (uid, jpeg bytes)
        self._seq = itertools.count(1)
        self._video_id = itertools.count(secrets.randbits(16))
        self._video_asm = FragmentReassembler(ttl=0.8, max_pending=3, latest_only=True)
        self._blob_asm = FragmentReassembler(ttl=6.0, max_pending=2)
        self.stop_event = threading.Event()
        self.thread = None
        self._last_rx = time.monotonic()
        self._started = time.monotonic()
        self._failed_reported = False

    # ------------------------------------------------------------------ отправка
    def _send(self, kind, payload=b""):
        data = encode(Packet(kind, self.user_id, next(self._seq), payload), self.password)
        self.transport.send(data, self.host)
        if self.stats:
            self.stats.on_send(len(data))

    def send_audio(self, payload: bytes):
        self._send(PacketType.AUDIO, payload)

    def send_sfx(self, payload: bytes):
        self._send(PacketType.SFX, payload)

    def send_music(self, payload: bytes):
        self._send(PacketType.MUSIC, payload)

    def send_video(self, jpeg: bytes):
        for frag in split_fragments(next(self._video_id), jpeg):
            self._send(PacketType.VIDEO, frag)

    def send_control(self, obj: dict):
        self._send(PacketType.CONTROL, pack_json(obj))

    def send_avatar(self, data: bytes):
        frags = split_fragments(secrets.randbits(32), data)

        def worker():
            for i, frag in enumerate(frags):
                self._send(PacketType.BLOB, frag)
                if i % 6 == 5:
                    time.sleep(0.002)
        threading.Thread(target=worker, daemon=True).start()

    def request_avatar(self, uid: int):
        self.send_control({"cmd": "avatar_get", "id": uid})

    # ------------------------------------------------------------------ жизненный цикл
    def start(self):
        self.transport.start(self._handle)
        self.connection_state.emit("connecting")
        self.thread = threading.Thread(target=self._run, name="client-heartbeat", daemon=True)
        self.thread.start()

    def _hello(self):
        self._send(PacketType.HELLO, pack_json({"nickname": self.nickname}))

    def _run(self):
        while not self.stop_event.is_set():
            now = time.monotonic()
            try:
                if not self.online:
                    self._hello()
                    if not self._failed_reported and now - self._started > 8 and not self.user_id:
                        self._failed_reported = True
                        self.connection_state.emit("failed")
                else:
                    self._send(PacketType.HEARTBEAT, struct.pack("!d", now))
                    if now - self._last_rx > 7:
                        self.online = False
                        self.connection_state.emit("reconnecting")
            except OSError:
                break
            self.stop_event.wait(1.0 if not self.online else 2.0)

    def leave(self):
        try:
            self.send_control({"cmd": "leave"})
        except Exception:
            pass

    def close(self):
        # после кика stop_event уже выставлен — но сокет всё равно надо закрыть (раньше он утекал)
        self.stop_event.set()
        self.transport.close()

    # ------------------------------------------------------------------ приём
    def _handle(self, raw, address):
        if address[0] != self.host[0]:
            return
        try:
            packet = decode(raw, self.password)
        except ValueError:
            if self.stats:
                self.stats.on_invalid()
            return
        if self.stats:
            self.stats.on_recv(len(raw))
        self._last_rx = time.monotonic()
        kind = packet.kind
        if kind == PacketType.AUDIO:
            if self.on_audio:
                self.on_audio(packet.sender_id, packet.payload)
        elif kind == PacketType.SFX:
            if self.on_sfx:
                self.on_sfx(packet.sender_id, packet.payload)
        elif kind == PacketType.MUSIC:
            if self.on_music:
                self.on_music(packet.payload)
        elif kind == PacketType.VIDEO:
            try:
                frame = self._video_asm.feed(packet.sender_id, packet.payload)
            except ValueError:
                return
            if frame is not None and self.on_video:
                self.on_video(packet.sender_id, frame)
        elif kind == PacketType.BLOB:
            try:
                blob = self._blob_asm.feed(packet.sender_id, packet.payload)
            except ValueError:
                return
            if blob is not None:
                self.avatar_received.emit(packet.sender_id, blob)
        elif kind == PacketType.WELCOME:
            data = unpack_json(packet.payload)
            first = not self.user_id
            self.user_id = int(data["user_id"])
            self.host_id = int(data.get("host_id", 0))
            self.is_host = bool(data.get("is_host"))
            room = str(data.get("room", ""))
            if room != self.room_name:
                self.room_name = room
                self.room_named.emit(room)
            was_online = self.online
            self.online = True
            if first or not was_online:
                self.connected.emit(self.user_id)
                self.connection_state.emit("online")
        elif kind == PacketType.USER_LIST:
            self.users_changed.emit(unpack_json(packet.payload))
        elif kind == PacketType.CONTROL:
            msg = unpack_json(packet.payload)
            if isinstance(msg, dict):
                msg["_sender"] = packet.sender_id
                self.control_received.emit(msg)
        elif kind == PacketType.PONG:
            try:
                rtt = (time.monotonic() - struct.unpack("!d", packet.payload[:8])[0]) * 1000
            except struct.error:
                return
            if self.stats:
                self.stats.last_rtt_ms = rtt
            self.rtt_changed.emit(rtt)
        elif kind == PacketType.KICK:
            self.kicked.emit()
            self.stop_event.set()
        elif kind == PacketType.ERROR:
            self.server_error.emit(packet.payload.decode("utf-8", "replace"))
