import os
import tempfile
import threading
import time
import unittest
import wave

import numpy as np

os.environ.setdefault("TREZVONILNIK_HOME", tempfile.mkdtemp(prefix="trz-test-"))

from media.music.bot import MusicBot, Track, TrackResolver, classify, parse_spotify_meta
from media.video.capture import CaptureSource, SourceGone
from media.video.streamer import VideoStreamer
from services.avatars import AvatarStore, process_avatar, avatar_hash

SR = 48000


def make_wav(path, seconds, freq=440):
    t = np.arange(int(SR * seconds)) / SR
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes((8000 * np.sin(2 * np.pi * freq * t)).astype(np.int16).tobytes())


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class ResolverTests(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify("https://open.spotify.com/track/abc"), "spotify")
        self.assertEqual(classify("https://youtu.be/xyz"), "url")
        self.assertEqual(classify("https://soundcloud.com/a/b"), "url")
        self.assertEqual(classify("daft punk one more time"), "search")

    def test_spotify_meta_parsing(self):
        page = ('<meta property="og:title" content="Blinding Lights"/>'
                '<meta property="og:description" content="The Weeknd · After Hours · Song · 2020"/>')
        self.assertEqual(parse_spotify_meta(page), ("Blinding Lights", "The Weeknd"))
        page2 = ('<meta property="og:description" content="Listen to Song on Spotify. Artist · Song · 2019"/>'
                 '<meta property="og:title" content="Song"/>')
        self.assertEqual(parse_spotify_meta(page2), ("Song", "Artist"))
        self.assertEqual(parse_spotify_meta("<html></html>"), ("", ""))

    def _resolver(self, info, calls, fetch=None):
        class FakeYDL:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def extract_info(s, q, download=False):
                calls.append(q)
                return info
        return TrackResolver(fetch=fetch or (lambda url: ""), ytdlp_factory=FakeYDL)

    def test_spotify_goes_through_youtube_search(self):
        calls = []
        page = '<meta property="og:title" content="Song"/><meta property="og:description" content="Artist · Song · 2019"/>'
        r = self._resolver({"entries": [{"title": "Song (Official)", "uploader": "Artist", "url": "http://a/b", "duration": 200,
                                         "http_headers": {"User-Agent": "x"}}]}, calls, fetch=lambda u: page)
        track = r.resolve("https://open.spotify.com/track/1", "Вася")
        self.assertEqual(calls, ["ytsearch1:Artist Song audio"])
        self.assertEqual((track.title, track.requested_by, track.source), ("Song (Official)", "Вася", "Spotify → YouTube"))

    def test_plain_text_is_searched_and_urls_passed_through(self):
        calls = []
        r = self._resolver({"title": "T", "url": "http://x", "duration": 10}, calls)
        r.resolve("lofi beats")
        r.resolve("https://soundcloud.com/a/b")
        self.assertEqual(calls, ["ytsearch1:lofi beats", "https://soundcloud.com/a/b"])

    def test_rejects_too_long_and_empty(self):
        r = self._resolver({"title": "T", "url": "http://x", "duration": 99999}, [])
        with self.assertRaises(ValueError):
            r.resolve("x")
        r = self._resolver({"entries": []}, [])
        with self.assertRaises(ValueError):
            r.resolve("x")


class FakeResolver:
    def __init__(self, tracks): self.tracks = tracks
    def resolve(self, query, by=""):
        if query == "bad":
            raise ValueError("не найдено")
        return Track(title=query, stream_url=self.tracks[query], requested_by=by)


class MusicBotTests(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.a, self.b = os.path.join(d, "a.wav"), os.path.join(d, "b.wav")
        make_wav(self.a, 1.0); make_wav(self.b, 0.4, 880)
        self.sent, self.local, self.msgs, self.states = [], [], [], []
        self.bot = MusicBot(self.sent.append, self.local.append, self.states.append, self.msgs.append,
                            FakeResolver({"a": self.a, "b": self.b}))

    def tearDown(self):
        self.bot.close()

    def test_plays_queue_in_order_in_real_time(self):
        t0 = time.monotonic()
        self.bot.add("a", "Петя"); self.bot.add("b", "Вася")
        self.assertTrue(wait_for(lambda: self.bot.current and self.bot.current.title == "a"))
        self.assertTrue(wait_for(lambda: self.bot.current and self.bot.current.title == "b", 4))
        self.assertTrue(wait_for(lambda: self.bot.current is None and len(self.local) >= 70, 4))
        took = time.monotonic() - t0
        self.assertAlmostEqual(len(self.sent), 70, delta=3)          # 1.0 с + 0.4 с = 70 кадров
        self.assertGreater(took, 1.2)                                # не залпом: идёт в реальном времени
        self.assertTrue(any("Играет: a" in m for m in self.msgs))

    def test_skip_pause_resume_stop(self):
        self.bot.add("a")
        self.assertTrue(wait_for(lambda: len(self.sent) > 5))
        self.bot.toggle_pause()
        time.sleep(0.15)
        n = len(self.sent)
        time.sleep(0.3)
        self.assertEqual(len(self.sent), n)                          # на паузе кадры не идут
        self.bot.toggle_pause()
        self.assertTrue(wait_for(lambda: len(self.sent) > n + 3))
        self.bot.add("b")
        self.assertTrue(wait_for(lambda: len(self.bot.queue) == 1))
        self.bot.skip()
        self.assertTrue(wait_for(lambda: self.bot.current and self.bot.current.title == "b"))
        self.bot.stop()
        self.assertTrue(wait_for(lambda: self.bot.current is None))
        self.assertEqual(self.bot.queue, [])

    def test_bad_query_reports_and_does_not_break_queue(self):
        self.bot.add("bad")
        self.assertTrue(wait_for(lambda: any("не найдено" in m for m in self.msgs)))
        self.bot.add("b")
        self.assertTrue(wait_for(lambda: self.bot.current and self.bot.current.title == "b"))

    def test_unplayable_stream_reports_error(self):
        self.bot.resolver = FakeResolver({"x": "/nonexistent/file.mp3"})
        self.bot.add("x")
        self.assertTrue(wait_for(lambda: any("Не удалось воспроизвести" in m for m in self.msgs)))
        self.assertTrue(wait_for(lambda: self.bot.current is None))

    def test_remote_commands(self):
        self.bot.handle_command({"action": "add", "url": "a", "nick": "Гость"})
        self.assertTrue(wait_for(lambda: self.bot.current is not None))
        self.assertEqual(self.bot.current.requested_by, "Гость")
        self.bot.handle_command({"action": "skip"})
        self.assertTrue(wait_for(lambda: self.bot.current is None))
        st = self.bot.state()
        self.assertEqual((st["cmd"], st["now"], st["queue"]), ("music_state", None, []))


class StreamerTests(unittest.TestCase):
    class FakeGrabber:
        def __init__(self, noisy=False): self.n, self.noisy, self.closed = 0, noisy, False
        def grab(self, source):
            self.n += 1
            rng = np.random.default_rng(self.n)
            if self.noisy:
                return rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
            img = np.zeros((720, 1280, 3), dtype=np.uint8); img[:, :640] = 200
            return img
        def close(self): self.closed = True

    SRC = CaptureSource("monitor", "Экран 1", {"left": 0, "top": 0, "width": 1280, "height": 720})

    def make(self, noisy=False, **kw):
        self.sent, self.local, self.ended = [], [], []
        g = self.FakeGrabber(noisy)
        s = VideoStreamer(self.sent.append, self.SRC, on_local_frame=self.local.append, on_ended=self.ended.append,
                          grabber_factory=lambda: g, **kw)
        self.g = g
        return s

    def test_no_viewers_means_no_encoding_and_no_traffic(self):
        s = self.make(fps=30)
        s.start(); time.sleep(0.4); s.stop()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.g.n, 0)                                # даже не захватываем экран

    def test_sends_when_watched_and_resizes(self):
        s = self.make(fps=30, width=640)
        s.viewers = 1; s.start()
        self.assertTrue(wait_for(lambda: len(self.sent) >= 3))
        s.stop()
        import cv2
        frame = cv2.imdecode(np.frombuffer(self.sent[0], np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(frame.shape[1], 640)
        self.assertTrue(self.g.closed)

    def test_self_view_without_network(self):
        s = self.make(fps=30)
        s.self_view = True; s.start()
        self.assertTrue(wait_for(lambda: len(self.local) >= 2))
        s.stop()
        self.assertEqual(self.sent, [])

    def test_quality_adapts_to_bitrate_budget(self):
        s = self.make(noisy=True, fps=20, width=1280, kbps=1500)     # бюджет ≈ 9.4 КБ/кадр — шум в него не влезает
        s.viewers = 1; s.start()
        self.assertTrue(wait_for(lambda: len(self.sent) >= 12))
        s.stop()
        self.assertEqual(s.quality, s.MIN_Q)                         # уткнулись в пол качества
        generous = self.make(fps=15, kbps=9000, width=1280)
        generous.viewers = 1; generous.start()
        self.assertTrue(wait_for(lambda: len(self.sent) >= 12))
        generous.stop()
        self.assertGreater(generous.quality, 70)                     # лёгкая картинка — качество растёт

    def test_ends_when_window_disappears(self):
        s = self.make(fps=30)
        s.grabber_factory = lambda: type("G", (), {"grab": lambda self, src: (_ for _ in ()).throw(SourceGone("x")),
                                                    "close": lambda self: None})()
        s.viewers = 1; s.start()
        self.assertTrue(wait_for(lambda: self.ended))
        self.assertIn("окно закрыто", self.ended[0])


class AvatarTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_static_avatar_is_square_and_small(self):
        from PIL import Image
        import io
        p = os.path.join(self.dir, "a.png")
        Image.effect_noise((900, 500), 60).convert("RGB").save(p)
        data, animated = process_avatar(p)
        self.assertFalse(animated)
        self.assertLessEqual(len(data), 90_000)
        img = Image.open(io.BytesIO(data))
        self.assertEqual(img.width, img.height)

    def test_animated_gif_stays_animated_and_fits(self):
        from PIL import Image
        import io
        frames = [Image.effect_noise((300, 300), 40 + i * 5).convert("RGB") for i in range(30)]
        p = os.path.join(self.dir, "a.gif")
        frames[0].save(p, save_all=True, append_images=frames[1:], duration=60, loop=0)
        data, animated = process_avatar(p)
        self.assertTrue(animated)
        self.assertLessEqual(len(data), 90_000)
        self.assertGreater(Image.open(io.BytesIO(data)).n_frames, 5)

    def test_store_is_content_addressed(self):
        store = AvatarStore(self.dir)
        h = store.put(b"abc")
        self.assertEqual(h, avatar_hash(b"abc"))
        self.assertEqual(AvatarStore(self.dir).get(h), b"abc")
        self.assertIsNone(store.get("deadbeef0000"))
        self.assertIsNone(store.get(""))


if __name__ == "__main__":
    unittest.main()
