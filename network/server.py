from __future__ import annotations
import hashlib
import itertools
import secrets
import threading
import time

from models.user import User
from network.protocol import (Packet, PacketType, VERSION, decode, encode, pack_json,
                              unpack_json, split_fragments)
from network.reassembly import FragmentReassembler
from network.transport import UdpTransport

MAX_USERS = 16
MAX_AVATAR_BYTES = 120_000
LOCAL_HOSTS = ("127.0.0.1", "::1")


class TokenBucket:
    def __init__(self, rate: float, burst: float):
        self.rate, self.burst = rate, burst
        self.tokens, self.t = burst, time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.burst, self.tokens + (now - self.t) * self.rate)
        self.t = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RoomServer:
    """UDP-реле комнаты. Всё, что касается прав (мьюты хоста, запреты, кик), решает сервер:
    клиент может быть сколь угодно «доработан» — пакеты запрещённого типа просто не уйдут дальше."""

    def __init__(self, password: str, port: int = 5000, on_users=None, room_name: str = ""):
        self.password = password
        self.room_name = room_name[:40]
        self.transport = UdpTransport("0.0.0.0", port, exclusive=True)
        self.on_users = on_users
        self.users: dict[int, User] = {}
        self.by_address: dict[tuple[str, int], int] = {}
        self.watchers: dict[int, set[int]] = {}
        self.avatars: dict[int, bytes] = {}
        self.host_id = secrets.randbits(31) or 1
        self._seq = itertools.count(1)
        self._blob_asm = FragmentReassembler(ttl=6.0, max_pending=2)
        self._buckets: dict[tuple[int, str], TokenBucket] = {}
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.maintenance_thread = None

    # ------------------------------------------------------------------ жизненный цикл
    def start(self):
        self.transport.start(self._handle)
        self.maintenance_thread = threading.Thread(target=self._maintenance, daemon=True)
        self.maintenance_thread.start()

    def close(self):
        self.stop_event.set()
        self.transport.close()

    # ------------------------------------------------------------------ отправка
    def _send(self, kind, sender_id, payload, address):
        self.transport.send(encode(Packet(kind, sender_id, next(self._seq), payload), self.password), address)

    def _control_to(self, user: User, obj: dict):
        self._send(PacketType.CONTROL, self.host_id, pack_json(obj), user.address)

    def _control_all(self, obj: dict, except_id: int | None = None):
        data = encode(Packet(PacketType.CONTROL, self.host_id, next(self._seq), pack_json(obj)), self.password)
        for uid, user in list(self.users.items()):
            if uid != except_id:
                self.transport.send(data, user.address)

    def _bucket(self, uid: int, name: str, rate: float, burst: float) -> TokenBucket:
        return self._buckets.setdefault((uid, name), TokenBucket(rate, burst))

    # ------------------------------------------------------------------ приём
    def _handle(self, raw, address):
        try:
            packet = decode(raw, self.password)
        except ValueError:
            return
        now = time.time()
        with self.lock:
            uid = self.by_address.get(address)
            if packet.kind == PacketType.HELLO:
                self._on_hello(packet, address, uid, now)
                return
            user = self.users.get(uid) if uid is not None else None
            if not user:
                return
            user.last_seen = now
            kind = packet.kind
            if kind == PacketType.HEARTBEAT:
                self._send(PacketType.PONG, self.host_id, packet.payload, address)
            elif kind == PacketType.AUDIO:
                if not user.mic_locked:
                    self._relay(packet, uid, [u for i, u in self.users.items() if i != uid])
            elif kind == PacketType.SFX:
                if not user.sfx_locked:
                    self._relay(packet, uid, [u for i, u in self.users.items() if i != uid])
            elif kind == PacketType.MUSIC:
                if user.is_host:
                    self._relay(packet, uid, [u for i, u in self.users.items() if i != uid])
            elif kind == PacketType.VIDEO:
                if user.sharing and not user.stream_locked:
                    targets = [self.users[v] for v in self.watchers.get(uid, ()) if v in self.users]
                    if targets:
                        self._relay(packet, uid, targets)
            elif kind == PacketType.BLOB:
                self._on_blob(user, packet)
            elif kind == PacketType.CONTROL:
                try:
                    msg = unpack_json(packet.payload)
                except Exception:
                    return
                if isinstance(msg, dict):
                    self._on_control(user, msg)

    def _relay(self, packet: Packet, uid: int, targets):
        data = encode(Packet(packet.kind, uid, packet.sequence, packet.payload), self.password)
        for peer in targets:
            self.transport.send(data, peer.address)

    def _new_id(self) -> int:
        uid = secrets.randbits(31) or 1
        while uid in self.users or uid == self.host_id:
            uid = secrets.randbits(31) or 1
        return uid

    def _on_hello(self, packet, address, uid, now):
        try:
            data = unpack_json(packet.payload)
        except Exception:
            return
        nickname = str(data.get("nickname", "Гость")).strip()[:32] or "Гость"
        created = False
        if uid is None:
            if len(self.users) >= MAX_USERS:
                self._send(PacketType.ERROR, self.host_id, "Комната заполнена".encode(), address)
                return
            is_host = self.host_id not in self.users and address[0] in LOCAL_HOSTS
            uid = self.host_id if is_host else self._new_id()
            self.users[uid] = User(uid, nickname, address, is_host=is_host)
            self.by_address[address] = uid
            created = True
        user = self.users[uid]
        user.last_seen = now
        if user.nickname != nickname:
            user.nickname = nickname
            created = True
        self._send(PacketType.WELCOME, self.host_id,
                   pack_json({"user_id": uid, "host_id": self.host_id, "is_host": user.is_host, "v": VERSION,
                              "room": self.room_name}),
                   address)
        if created:
            self._broadcast_users()

    # ------------------------------------------------------------------ аватарки
    def _on_blob(self, user: User, packet: Packet):
        try:
            data = self._blob_asm.feed(user.user_id, packet.payload)
        except ValueError:
            return
        if data is None or len(data) > MAX_AVATAR_BYTES:
            return
        digest = hashlib.sha1(data).hexdigest()[:12]
        self.avatars[user.user_id] = data
        user.avatar_hash = digest
        self._broadcast_users()

    def _send_avatar(self, target: User, owner_id: int):
        data = self.avatars.get(owner_id)
        if not data:
            return
        msg_id = secrets.randbits(32)

        def worker():
            for i, frag in enumerate(split_fragments(msg_id, data)):
                self._send(PacketType.BLOB, owner_id, frag, target.address)
                if i % 6 == 5:
                    time.sleep(0.002)      # не заливаем очередь VPN залпом
        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ команды
    def _on_control(self, user: User, msg: dict):
        cmd = msg.get("cmd")
        uid = user.user_id
        if cmd == "leave":
            self._drop_user(uid)
        elif cmd == "state":
            muted, deaf = bool(msg.get("muted")), bool(msg.get("deafened"))
            if (muted, deaf) != (user.muted, user.deafened):
                user.muted, user.deafened = muted, deaf
                self._broadcast_users()
        elif cmd == "stream":
            on = bool(msg.get("on"))
            if on and user.stream_locked:
                self._control_to(user, {"cmd": "stop_stream", "reason": "Хост запретил вам трансляции"})
                return
            user.sharing = on
            user.stream_title = str(msg.get("title", ""))[:40] if on else ""
            if not on:
                self.watchers.pop(uid, None)
            self._broadcast_users()
        elif cmd == "watch":
            target, on = msg.get("target"), bool(msg.get("on"))
            if target in self.users and target != uid:
                group = self.watchers.setdefault(target, set())
                group.add(uid) if on else group.discard(uid)
                self._notify_watchers(target)
        elif cmd == "react":
            if self._bucket(uid, "react", 14, 30).allow():
                emoji = str(msg.get("emoji", ""))[:8]
                if emoji:
                    self._control_all({"cmd": "react", "from": uid, "emoji": emoji}, except_id=uid)
        elif cmd == "avatar_get":
            owner = msg.get("id")
            if owner in self.avatars and self._bucket(uid, "avatar", 1.0, 6).allow():
                self._send_avatar(user, owner)
        elif cmd == "avatar_clear":
            if self.avatars.pop(uid, None) is not None:
                user.avatar_hash = ""
                self._broadcast_users()
        elif cmd == "wheel":
            if self._bucket(uid, "wheel", 0.5, 2).allow():
                out = self._clean_wheel(msg)
                if out:
                    out["from"] = uid
                    self._control_all(out, except_id=uid)
        elif cmd == "music":
            host = self.users.get(self.host_id)
            if host and self._bucket(uid, "music", 1.0, 5).allow():
                msg = {k: msg[k] for k in ("action", "url", "index", "value") if k in msg}
                msg.update(cmd="music", **{"from": uid})
                if isinstance(msg.get("url"), str):
                    msg["url"] = msg["url"][:500]
                self._control_to(host, msg)
        elif cmd == "music_state":
            if user.is_host:
                self._control_all(msg, except_id=uid)
        elif cmd == "admin":
            if user.is_host:
                self._on_admin(msg)

    @staticmethod
    def _clean_wheel(msg: dict):
        options, weights = msg.get("options"), msg.get("weights")
        winner, turns = msg.get("winner"), msg.get("turns")
        if (not isinstance(options, list) or not 2 <= len(options) <= 32 or
                not isinstance(weights, list) or len(weights) != len(options)):
            return None
        try:
            return {"cmd": "wheel",
                    "options": [str(o)[:40] for o in options],
                    "weights": [max(0.01, float(w)) for w in weights],
                    "winner": int(winner) % len(options),
                    "offset": min(1.0, max(0.0, float(msg.get("offset", 0.5)))),
                    "turns": min(12.0, max(2.0, float(turns)))}
        except (TypeError, ValueError):
            return None

    def _on_admin(self, msg: dict):
        target = self.users.get(msg.get("target"))
        action, value = msg.get("action"), bool(msg.get("value", True))
        if not target or target.is_host:
            return
        if action == "kick":
            self._kick(target)
            return
        if action == "stop_stream":
            self._stop_stream(target, "Хост остановил вашу трансляцию")
        elif action == "lock_mic":
            target.mic_locked = value
        elif action == "lock_sfx":
            target.sfx_locked = value
        elif action == "lock_stream":
            target.stream_locked = value
            if value:
                self._stop_stream(target, "Хост запретил вам трансляции")
        else:
            return
        self._broadcast_users()

    def _stop_stream(self, target: User, reason: str):
        target.sharing = False
        target.stream_title = ""
        self.watchers.pop(target.user_id, None)
        self._control_to(target, {"cmd": "stop_stream", "reason": reason})

    def _notify_watchers(self, streamer_id: int):
        streamer = self.users.get(streamer_id)
        if streamer:
            self._control_to(streamer, {"cmd": "watchers", "count": len(self.watchers.get(streamer_id, ()))})

    # ------------------------------------------------------------------ пользователи
    def _drop_user(self, uid: int):
        user = self.users.pop(uid, None)
        if not user:
            return None
        self.by_address.pop(user.address, None)
        self.avatars.pop(uid, None)
        self.watchers.pop(uid, None)
        self._blob_asm.forget(uid)
        for streamer, group in list(self.watchers.items()):
            if uid in group:
                group.discard(uid)
                self._notify_watchers(streamer)
        for key in [k for k in self._buckets if k[0] == uid]:
            self._buckets.pop(key, None)
        self._broadcast_users()
        return user

    def _kick(self, user: User):
        self._send(PacketType.KICK, self.host_id, b"", user.address)
        self._drop_user(user.user_id)

    def kick(self, user_id: int) -> bool:
        with self.lock:
            user = self.users.get(user_id)
            if not user or user.is_host:
                return False
            self._kick(user)
            return True

    def _broadcast_users(self):
        payload = pack_json([u.public() for u in self.users.values()])
        for user in list(self.users.values()):
            self._send(PacketType.USER_LIST, self.host_id, payload, user.address)
        if self.on_users:
            self.on_users(list(self.users.values()))

    def _maintenance(self):
        while not self.stop_event.wait(1.0):
            with self.lock:
                now = time.time()
                for uid in [uid for uid, u in self.users.items() if now - u.last_seen > 8]:
                    self._drop_user(uid)
