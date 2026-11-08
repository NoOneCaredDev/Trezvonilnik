"""Два настоящих CallSession (хост + гость) в одном процессе: сеть, звук, стрим, музыка, админка — end-to-end."""
import os
import socket
import sys
import tempfile
import time
import types
import unittest
import wave
from functools import partial

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["TREZVONILNIK_HOME"] = tempfile.mkdtemp(prefix="trz-sess-")

import numpy as np
from PySide6.QtWidgets import QApplication
from PIL import Image

app = QApplication.instance() or QApplication([])

import app.session as session_mod
from app.session import CallSession
from config.settings import AppSettings
from media.video.capture import CaptureSource
from media.video.streamer import VideoStreamer

SR = 48000


class FakeStream:
    def __init__(self, **kw): pass
    def start(self): pass
    def stop(self): pass
    def close(self): pass


def install_fake_sd():
    sd = types.ModuleType("sounddevice")
    sd.InputStream = lambda **kw: FakeStream()
    sd.OutputStream = lambda **kw: FakeStream()
    sys.modules["sounddevice"] = sd


class FakeGrabber:
    def grab(self, source):
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        img[:, :320] = (200, 80, 40)
        return img
    def close(self): pass


class FakeResolver:
    def __init__(self, path): self.path = path
    def resolve(self, query, by=""):
        from media.music.bot import Track
        return Track(title=query, artist="Тест", stream_url=self.path, requested_by=by, duration=1.0)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(cond, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    app.processEvents()
    return cond()


def tone(n=960, amp=9000):
    return (amp * np.sin(2 * np.pi * 440 * np.arange(n) / SR)).astype(np.int16)


class SessionFlow(unittest.TestCase):
    def setUp(self):
        install_fake_sd()
        self.port = free_port()
        mk = lambda: AppSettings(network_port=self.port, noise_suppression=False)
        self.host = CallSession("Хост", True, "", "pw", mk(), room_name="ИСТИННЫЕ НАТУРАЛЫ")
        self.host.start()
        self.assertTrue(wait_for(lambda: self.host.my_id))
        self.guest = CallSession("Гость", False, "127.0.0.1", "pw", mk())
        self.guest.start()
        self.assertTrue(wait_for(lambda: len(self.guest.users) == 2 and len(self.host.users) == 2))
        self.gid, self.hid = self.guest.my_id, self.host.my_id
        self.toasts_g, self.toasts_h = [], []
        self.guest.toast.connect(lambda t, k: self.toasts_g.append(t))
        self.host.toast.connect(lambda t, k: self.toasts_h.append(t))

    def tearDown(self):
        self.guest.close()
        self.host.close()
        sys.modules.pop("sounddevice", None)

    def test_room_and_roles(self):
        self.assertEqual(self.guest.room_name, "ИСТИННЫЕ НАТУРАЛЫ")
        self.assertTrue(self.host.me()["host"])
        self.assertFalse(self.guest.me()["host"])

    def test_deafen_also_mutes_and_restores_previous_state(self):
        self.guest.set_deafened(True)
        self.assertTrue(wait_for(lambda: self.host.user(self.gid)["deafened"] and self.host.user(self.gid)["muted"]))
        self.guest.set_deafened(False)
        self.assertTrue(wait_for(lambda: not self.host.user(self.gid)["deafened"] and not self.host.user(self.gid)["muted"]))
        self.guest.set_muted(True)
        self.guest.set_deafened(True)
        self.guest.set_deafened(False)
        self.assertTrue(self.guest.engine.muted)               # был замьючен до «оглохнуть» — так и остался

    def test_host_lock_mic_blocks_unmute_and_voice(self):
        self.guest.set_muted(True)
        self.host.admin("lock_mic", self.gid)
        self.assertTrue(wait_for(lambda: self.guest.me().get("mic_locked")))
        self.assertTrue(any("запретил" in t and "микрофон" in t for t in self.toasts_g))
        self.guest.set_muted(False)
        self.assertTrue(self.guest.engine.muted)                # снять мьют нельзя
        self.guest.client.send_audio(b"x")
        wait_for(lambda: False, 0.3)

    def test_voice_arrives_and_speaking_indicator_works(self):
        frame = self.guest.engine.encoder.encode(tone())
        for _ in range(4):
            self.guest.client.send_audio(frame)
        self.assertTrue(wait_for(lambda: (self.gid, "voice") in self.host.engine.mixer.channels))
        self.assertTrue(self.host.levels()[self.gid][0])        # на карточке загорится «говорит»
        self.host.mute_user(self.gid, True)
        self.assertFalse(self.host.levels()[self.gid][0])

    def test_reaction_reaches_others(self):
        got = []
        self.host.reaction.connect(lambda uid, e: got.append((uid, e)))
        self.guest.send_reaction("💩")
        self.assertTrue(wait_for(lambda: got))
        self.assertEqual(got[0], (self.gid, "💩"))

    def test_soundpad_sfx_reaches_host_and_lock_works(self):
        wav = os.path.join(tempfile.mkdtemp(), "s.wav")
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
            wf.writeframes(tone(SR // 2).tobytes())
        sound = self.guest.add_sound(wav, "Тест", "🎺", 100)
        self.guest.play_sound(sound.id)
        self.assertTrue(wait_for(lambda: (self.gid, "sfx") in self.host.engine.mixer.channels))
        self.guest.player._thread.join(2)
        self.host.admin("lock_sfx", self.gid)
        self.assertTrue(wait_for(lambda: self.guest.me().get("sfx_locked")))
        before = self.toasts_g.count("Хост запретил вам саундпад")
        self.guest.play_sound(sound.id)
        self.assertEqual(self.toasts_g.count("Хост запретил вам саундпад"), before + 1)
        self.assertFalse(self.guest.player.playing)

    def test_local_sfx_mute_per_user(self):
        self.host.mute_user_sfx(self.gid, True)
        self.assertEqual(self.host.user_local(self.gid), {"volume": 100, "muted": False, "sfx_muted": True})

    def test_screen_share_end_to_end_with_viewer_subscription(self):
        session_mod.VideoStreamer = partial(VideoStreamer, grabber_factory=FakeGrabber)
        try:
            frames = []
            self.host.stream_frame.connect(frames.append)
            ok = self.guest.start_stream(CaptureSource("monitor", "Экран 1", {"left": 0, "top": 0, "width": 640, "height": 360}), "low")
            self.assertTrue(ok)
            self.assertTrue(wait_for(lambda: self.host.user(self.gid).get("sharing")))
            self.assertTrue(any("начал(а) трансляцию" in t for t in self.toasts_h))
            wait_for(lambda: False, 0.4)
            self.assertEqual(frames, [])                         # никто не смотрит → ничего не идёт
            self.assertEqual(self.guest.streamer.frames_sent, 0)
            self.host.watch(self.gid)
            self.assertTrue(wait_for(lambda: self.guest.watchers == 1))
            self.assertTrue(wait_for(lambda: frames, 5))
            self.assertEqual((frames[0].width(), frames[0].height()), (640, 360))
            self.assertGreater(self.guest.streamer.frames_sent, 0)
            self.host.unwatch()
            self.assertTrue(wait_for(lambda: self.guest.watchers == 0))
        finally:
            session_mod.VideoStreamer = VideoStreamer

    def test_host_can_stop_and_forbid_streams(self):
        session_mod.VideoStreamer = partial(VideoStreamer, grabber_factory=FakeGrabber)
        try:
            src = CaptureSource("monitor", "Экран 1", {"left": 0, "top": 0, "width": 640, "height": 360})
            self.guest.start_stream(src)
            self.assertTrue(wait_for(lambda: self.host.user(self.gid).get("sharing")))
            self.host.admin("stop_stream", self.gid)
            self.assertTrue(wait_for(lambda: not self.guest.sharing))
            self.assertTrue(wait_for(lambda: not self.host.user(self.gid).get("sharing")))
            self.host.admin("lock_stream", self.gid)
            self.assertTrue(wait_for(lambda: self.guest.me().get("stream_locked")))
            self.assertFalse(self.guest.start_stream(src))
        finally:
            session_mod.VideoStreamer = VideoStreamer

    def test_stream_dies_cleanly_when_window_closes(self):
        from media.video.capture import SourceGone
        class Gone:
            def grab(self, s): raise SourceGone("closed")
            def close(self): pass
        session_mod.VideoStreamer = partial(VideoStreamer, grabber_factory=Gone)
        try:
            self.guest.start_stream(CaptureSource("window", "Окно", None))
            self.guest.streamer.viewers = 1
            self.assertTrue(wait_for(lambda: not self.guest.sharing))
            self.assertTrue(any("Трансляция остановлена" in t for t in self.toasts_g))
        finally:
            session_mod.VideoStreamer = VideoStreamer

    def test_avatar_syncs_and_local_override_wins(self):
        src = os.path.join(tempfile.mkdtemp(), "me.png")
        Image.new("RGB", (400, 300), (30, 160, 90)).save(src)
        self.guest.set_avatar(src)
        self.assertTrue(wait_for(lambda: self.host.user(self.gid).get("avatar")))
        self.assertTrue(wait_for(lambda: self.gid in self.host.avatar_data))
        self.assertEqual(self.host.avatar_data[self.gid], self.guest.avatar_data[self.gid])
        other = os.path.join(tempfile.mkdtemp(), "x.png")
        Image.new("RGB", (64, 64), (200, 0, 0)).save(other)
        self.host.set_local_avatar("Гость", other)
        self.assertNotEqual(self.host.avatar_for(self.gid), self.host.avatar_data[self.gid])
        self.host.set_local_avatar("Гость", None)
        self.assertEqual(self.host.avatar_for(self.gid), self.host.avatar_data[self.gid])
        self.guest.set_avatar(None)
        self.assertTrue(wait_for(lambda: self.gid not in self.host.avatar_data))

    def test_guest_queues_music_on_host_bot_and_everyone_sees_state(self):
        wav = os.path.join(tempfile.mkdtemp(), "m.wav")
        with wave.open(wav, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
            wf.writeframes(tone(SR).tobytes())
        self.host.bot.resolver = FakeResolver(wav)
        self.guest.music_command({"action": "add", "url": "песенка"})
        self.assertTrue(wait_for(lambda: (self.guest.music.get("now") or {}).get("title") == "песенка", 5))
        self.assertEqual(self.guest.music["now"]["by"], "Гость")
        self.assertTrue(wait_for(lambda: (0, "music") in self.guest.engine.mixer.channels))   # звук реально дошёл
        notices = []
        self.guest.music_notice.connect(notices.append)
        self.guest.music_command({"action": "stop"})
        self.assertTrue(wait_for(lambda: self.guest.music.get("now") is None))

    def test_wheel_is_shown_to_everyone_with_author(self):
        got = []
        self.host.wheel_remote.connect(lambda m, who: got.append((m, who)))
        self.guest.send_wheel({"options": ["a", "b"], "weights": [1, 1], "winner": 1, "offset": 0.5, "turns": 6})
        self.assertTrue(wait_for(lambda: got))
        self.assertEqual((got[0][1], got[0][0]["winner"]), ("Гость", 1))

    def test_join_leave_toasts_and_cleanup(self):
        late = CallSession("Опоздун", False, "127.0.0.1", "pw", AppSettings(network_port=self.port))
        late.start()
        try:
            self.assertTrue(wait_for(lambda: any("Опоздун зашёл" in t for t in self.toasts_h)))
        finally:
            late.close()
        self.assertTrue(wait_for(lambda: any("Опоздун вышел" in t for t in self.toasts_h)))
        self.assertTrue(wait_for(lambda: len(self.host.users) == 2))

    def test_settings_snapshot_restore_and_voice_effect(self):
        snap = self.host.snapshot_settings()
        self.host.settings.voice_effect = "robot"
        self.host.settings.output_volume = 30
        self.host.engine.apply_settings()
        self.assertEqual(self.host.voice_changer.effect, "robot")
        self.assertAlmostEqual(self.host.engine.mixer.master, 0.3)
        self.host.restore_settings(snap)
        self.assertEqual(self.host.voice_changer.effect, "none")
        self.assertEqual(self.host.engine.mixer.master, 1.0)

    def test_port_in_use_is_a_readable_error(self):
        from app.session import SessionError
        with self.assertRaises(SessionError) as cm:
            CallSession("Дубль", True, "", "pw", AppSettings(network_port=self.port))
        self.assertIn(str(self.port), str(cm.exception))


if __name__ == "__main__":
    unittest.main()
