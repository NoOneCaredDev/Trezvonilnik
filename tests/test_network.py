"""Интеграционные тесты: настоящий сервер и клиенты на loopback-UDP."""
import os
import socket
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication

from network.client import RoomClient
from network.protocol import Packet, PacketType, encode
from network.server import RoomServer

PW = "test-pass"
_app = QApplication.instance() or QApplication([])


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(cond, timeout=3.0):
    """Ждём условие, прокачивая очередь событий Qt (сигналы из сетевых потоков ставятся в очередь)."""
    end = time.time() + timeout
    while time.time() < end:
        _app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    _app.processEvents()
    return cond()


class Peer:
    """Клиент + всё, что он получил."""
    def __init__(self, name, port, password=PW):
        self.client = RoomClient(name, "127.0.0.1", password, port)
        self.users, self.controls, self.audio, self.sfx, self.music, self.video = [], [], [], [], [], []
        self.avatars = []
        c = self.client
        c.users_changed.connect(lambda u: setattr(self, "users", u))
        c.control_received.connect(self.controls.append)
        c.avatar_received.connect(lambda uid, b: self.avatars.append((uid, b)))
        c.on_audio = lambda uid, p: self.audio.append((uid, p))
        c.on_sfx = lambda uid, p: self.sfx.append((uid, p))
        c.on_music = self.music.append
        c.on_video = lambda uid, f: self.video.append((uid, f))
        c.start()

    def user(self, uid):
        return next((u for u in self.users if u["id"] == uid), None)

    def cmds(self, name):
        return [m for m in self.controls if m.get("cmd") == name]


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.port = free_port()
        self.server = RoomServer(PW, self.port)
        self.server.start()
        self.host = Peer("Хост", self.port)
        self.assertTrue(wait_for(lambda: self.host.client.user_id))
        self.guest = Peer("Гость", self.port)
        self.assertTrue(wait_for(lambda: self.guest.client.user_id and len(self.guest.users) == 2))
        self.hid, self.gid = self.host.client.user_id, self.guest.client.user_id

    def tearDown(self):
        for p in (self.host, self.guest):
            p.client.close()
        self.server.close()

    def test_first_loopback_client_is_host(self):
        self.assertTrue(self.host.client.is_host)
        self.assertFalse(self.guest.client.is_host)
        self.assertTrue(self.host.user(self.hid)["host"])
        self.assertFalse(self.host.user(self.gid)["host"])

    def test_audio_relay_uses_server_assigned_sender(self):
        self.guest.client.send_audio(b"\x01voice")
        self.assertTrue(wait_for(lambda: self.host.audio))
        self.assertEqual(self.host.audio[0], (self.gid, b"\x01voice"))
        self.assertEqual(self.guest.audio, [])          # себя не слышим

    def test_mic_lock_is_enforced_by_server(self):
        self.host.client.send_control({"cmd": "admin", "action": "lock_mic", "target": self.gid, "value": True})
        self.assertTrue(wait_for(lambda: (self.host.user(self.gid) or {}).get("mic_locked")))
        self.guest.client.send_audio(b"blocked")
        wait_for(lambda: False, 0.25)
        self.assertEqual(self.host.audio, [])
        self.host.client.send_control({"cmd": "admin", "action": "lock_mic", "target": self.gid, "value": False})
        self.assertTrue(wait_for(lambda: not self.host.user(self.gid)["mic_locked"]))
        self.guest.client.send_audio(b"ok")
        self.assertTrue(wait_for(lambda: self.host.audio))

    def test_sfx_lock(self):
        self.host.client.send_control({"cmd": "admin", "action": "lock_sfx", "target": self.gid})
        self.assertTrue(wait_for(lambda: self.host.user(self.gid)["sfx_locked"]))
        self.guest.client.send_sfx(b"boom")
        wait_for(lambda: False, 0.25)
        self.assertEqual(self.host.sfx, [])

    def test_guest_cannot_use_admin_commands(self):
        self.guest.client.send_control({"cmd": "admin", "action": "kick", "target": self.hid})
        self.guest.client.send_control({"cmd": "admin", "action": "lock_mic", "target": self.hid})
        wait_for(lambda: False, 0.4)
        self.assertEqual(len(self.host.users), 2)
        self.assertFalse(self.host.user(self.hid)["mic_locked"])

    def test_host_cannot_be_targeted(self):
        self.host.client.send_control({"cmd": "admin", "action": "kick", "target": self.hid})
        wait_for(lambda: False, 0.25)
        self.assertEqual(len(self.host.users), 2)

    def test_kick(self):
        self.host.client.send_control({"cmd": "admin", "action": "kick", "target": self.gid})
        self.assertTrue(wait_for(lambda: len(self.host.users) == 1))

    def test_video_goes_only_to_watchers_and_reassembles(self):
        self.guest.client.send_control({"cmd": "stream", "on": True, "title": "Экран 1"})
        self.assertTrue(wait_for(lambda: (self.host.user(self.gid) or {}).get("sharing")))
        frame = os.urandom(40_000)
        self.guest.client.send_video(frame)
        wait_for(lambda: False, 0.35)
        self.assertEqual(self.host.video, [])             # никто не смотрит — трафик не ходит
        self.host.client.send_control({"cmd": "watch", "target": self.gid, "on": True})
        self.assertTrue(wait_for(lambda: any(m["count"] == 1 for m in self.guest.cmds("watchers"))))
        self.guest.client.send_video(frame)
        self.assertTrue(wait_for(lambda: self.host.video))
        self.assertEqual(self.host.video[-1], (self.gid, frame))

    def test_stream_lock_stops_and_blocks_stream(self):
        self.guest.client.send_control({"cmd": "stream", "on": True})
        self.assertTrue(wait_for(lambda: (self.host.user(self.gid) or {}).get("sharing")))
        self.host.client.send_control({"cmd": "admin", "action": "lock_stream", "target": self.gid})
        self.assertTrue(wait_for(lambda: self.guest.cmds("stop_stream")))
        self.assertTrue(wait_for(lambda: not self.host.user(self.gid)["sharing"]))
        self.guest.controls.clear()
        self.guest.client.send_control({"cmd": "stream", "on": True})
        self.assertTrue(wait_for(lambda: self.guest.cmds("stop_stream")))
        self.assertFalse(self.host.user(self.gid)["sharing"])

    def test_stop_stream_without_lock(self):
        self.guest.client.send_control({"cmd": "stream", "on": True})
        self.assertTrue(wait_for(lambda: (self.host.user(self.gid) or {}).get("sharing")))
        self.host.client.send_control({"cmd": "admin", "action": "stop_stream", "target": self.gid})
        self.assertTrue(wait_for(lambda: self.guest.cmds("stop_stream")))
        self.assertFalse(self.host.user(self.gid)["stream_locked"])

    def test_reactions_broadcast_and_rate_limited(self):
        self.guest.client.send_control({"cmd": "react", "emoji": "💩"})
        self.assertTrue(wait_for(lambda: self.host.cmds("react")))
        self.assertEqual(self.host.cmds("react")[0]["from"], self.gid)
        self.host.controls.clear()
        for _ in range(200):
            self.guest.client.send_control({"cmd": "react", "emoji": "🔥"})
        wait_for(lambda: False, 0.6)
        self.assertLess(len(self.host.cmds("react")), 60)      # спам режется на сервере

    def test_avatar_roundtrip(self):
        blob = os.urandom(30_000)
        self.guest.client.send_avatar(blob)
        self.assertTrue(wait_for(lambda: (self.host.user(self.gid) or {}).get("avatar")))
        self.host.client.request_avatar(self.gid)
        self.assertTrue(wait_for(lambda: self.host.avatars))
        self.assertEqual(self.host.avatars[0], (self.gid, blob))

    def test_music_only_from_host_and_commands_reach_host(self):
        self.guest.client.send_music(b"fake")
        wait_for(lambda: False, 0.25)
        self.assertEqual(self.host.music, [])
        self.host.client.send_music(b"real")
        self.assertTrue(wait_for(lambda: self.guest.music))
        self.assertEqual(self.guest.music[0], b"real")
        self.guest.client.send_control({"cmd": "music", "action": "add", "url": "https://x/y"})
        self.assertTrue(wait_for(lambda: self.host.cmds("music")))
        m = self.host.cmds("music")[0]
        self.assertEqual((m["action"], m["url"], m["from"]), ("add", "https://x/y", self.gid))

    def test_wheel_validation(self):
        self.guest.client.send_control({"cmd": "wheel", "options": ["a", "b", "c"], "weights": [1, 1, 2],
                                        "winner": 2, "turns": 5})
        self.assertTrue(wait_for(lambda: self.host.cmds("wheel")))
        self.host.controls.clear()
        self.guest.client.send_control({"cmd": "wheel", "options": ["a"], "weights": [1], "winner": 0, "turns": 5})
        wait_for(lambda: False, 0.25)
        self.assertEqual(self.host.cmds("wheel"), [])

    def test_leave_is_immediate(self):
        self.guest.client.leave()
        self.assertTrue(wait_for(lambda: len(self.host.users) == 1, timeout=1.0))

    def test_room_name_reaches_guest(self):
        self.server.room_name = "ИСТИННЫЕ НАТУРАЛЫ"
        late = Peer("Поздний", self.port)
        try:
            self.assertTrue(wait_for(lambda: late.client.user_id))
            self.assertEqual(late.client.room_name, "ИСТИННЫЕ НАТУРАЛЫ")
        finally:
            late.client.close()

    def test_rtt_is_measured(self):
        got = []
        self.host.client.rtt_changed.connect(got.append)
        self.assertTrue(wait_for(lambda: got, timeout=4.0))
        self.assertLess(got[0], 100)


class WrongPasswordTest(unittest.TestCase):
    def test_wrong_password_reports_failure(self):
        port = free_port()
        server = RoomServer(PW, port)
        server.start()
        states = []
        client = RoomClient("X", "127.0.0.1", "WRONG", port)
        client.connection_state.connect(states.append)
        client._started -= 10
        client.start()
        try:
            self.assertTrue(wait_for(lambda: "failed" in states, timeout=3))
            self.assertEqual(server.users, {})
        finally:
            client.close()
            server.close()


if __name__ == "__main__":
    unittest.main()
