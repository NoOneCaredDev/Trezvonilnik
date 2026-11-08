import os
import sys
import tempfile
import time
import types
import unittest
import wave

import numpy as np

os.environ.setdefault("TREZVONILNIK_HOME", tempfile.mkdtemp(prefix="trz-test-"))

from config.settings import AppSettings
from media.audio.effects import VoiceChanger
from media.audio.engine import AudioEngine, FRAME
from media.audio.soundboard import SoundLibrary, SoundPlayer, decode_audio_file
from plugins.chain import AudioProcessorChain

SR = 48000


def tone(freq, n=FRAME, start=0, amp=9000):
    return (amp * np.sin(2 * np.pi * freq * (np.arange(n) + start) / SR)).astype(np.int16)


class FakeStream:
    def __init__(self, **kw):
        self.kw, self.started = kw, False
    def start(self): self.started = True
    def stop(self): self.started = False
    def close(self): pass


class FakeSD(types.ModuleType):
    def __init__(self):
        super().__init__("sounddevice")
        self.streams = []
    def InputStream(self, **kw):
        s = FakeStream(**kw); self.streams.append(s); return s
    def OutputStream(self, **kw):
        s = FakeStream(**kw); self.streams.append(s); return s


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.sd = FakeSD()
        sys.modules["sounddevice"] = self.sd
        self.sent = []
        self.settings = AppSettings(noise_suppression=False)
        self.vc = VoiceChanger()
        self.engine = AudioEngine(self.sent.append, self.settings, AudioProcessorChain([self.vc]), self.vc)

    def tearDown(self):
        self.engine.close()
        sys.modules.pop("sounddevice", None)

    def feed(self, samples):
        self.engine._capture(samples.reshape(-1, 1), len(samples), None, None)

    def test_starts_streams_with_callbacks(self):
        self.assertTrue(self.engine.start())
        self.assertEqual(len(self.sd.streams), 2)
        self.assertTrue(all(s.started for s in self.sd.streams))

    def test_start_failure_is_reported_not_raised(self):
        def boom(**kw): raise OSError("нет устройства")
        self.sd.InputStream = boom
        self.assertFalse(self.engine.start())
        self.assertIn("нет устройства", self.engine.error)

    def test_gate_blocks_silence_and_passes_speech(self):
        self.engine.running = True
        for _ in range(5):
            self.feed(np.zeros(FRAME, dtype=np.int16))
        self.assertEqual(self.sent, [])
        self.feed(tone(440))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.engine.speaking)

    def test_mute_sends_nothing_but_meter_works(self):
        self.engine.running = True
        self.engine.muted = True
        self.feed(tone(440))
        self.assertEqual(self.sent, [])
        self.assertGreater(self.engine.input_level_db, -30)

    def test_odd_block_sizes_are_reframed(self):
        self.engine.running = True
        self.feed(tone(440, 500))
        self.assertEqual(len(self.sent), 0)
        self.feed(tone(440, 1500, start=500))
        self.assertEqual(len(self.sent), 2)                 # 2000 сэмплов → 2 кадра по 960, 80 в остатке

    def test_mic_gain_changes_level(self):
        self.engine.running = True
        self.feed(tone(440, amp=2000)); a = self.engine.input_level_db
        self.settings.mic_gain = 200
        self.feed(tone(440, amp=2000)); b = self.engine.input_level_db
        self.assertAlmostEqual(b - a, 6.0, delta=0.5)

    def test_voice_effect_is_applied_live_from_settings(self):
        self.settings.voice_effect = "robot"
        self.engine.apply_settings()
        self.assertEqual(self.vc.effect, "robot")

    def test_each_remote_speaker_gets_their_own_decoder(self):
        from media.audio.codec import VoiceEncoder
        enc = VoiceEncoder()
        self.engine.receive(1, enc.encode(tone(440)))
        self.engine.receive(2, enc.encode(tone(880)), "sfx")
        self.assertEqual(set(self.engine.decoders), {(1, "voice"), (2, "sfx")})
        self.engine.forget(1)
        self.assertNotIn((1, "voice"), self.engine.decoders)

    def test_deafen_silences_output_but_keeps_draining(self):
        from media.audio.codec import VoiceEncoder
        enc = VoiceEncoder()
        for i in range(3):
            self.engine.receive(1, enc.encode(tone(440, start=i * FRAME)))
        out = np.zeros((FRAME, 1), dtype=np.int16)
        self.engine.deafened = True
        self.engine._playback(out, FRAME, None, None)
        self.assertFalse(out.any())
        self.engine.deafened = False
        self.engine._playback(out, FRAME, None, None)
        self.assertTrue(out.any())                           # не накопили задержку, пока были «в глухой»?

    def test_monitor_loops_processed_mic_to_self_channel(self):
        self.engine.running, self.engine.monitor = True, True
        for _ in range(3):
            self.feed(tone(440))
        self.assertIn((0, "self"), self.engine.mixer.channels)


class PathsTests(unittest.TestCase):
    def test_default_storage_is_appdata_like_not_temp(self):
        from unittest import mock
        from app import paths
        home = tempfile.mkdtemp(prefix="trz-home-")
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": home}, clear=False):
            os.environ.pop("TREZVONILNIK_HOME", None)
            with mock.patch.object(sys, "platform", "linux"):
                self.assertEqual(str(paths.sounds_dir()), os.path.join(home, "trezvonilnik", "sounds"))
        with mock.patch.dict(os.environ, {"APPDATA": home}, clear=False):
            os.environ.pop("TREZVONILNIK_HOME", None)
            with mock.patch.object(sys, "platform", "win32"):
                self.assertEqual(str(paths.data_dir()), os.path.join(home, "Trezvonilnik"))


class SoundboardTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="trz-snd-")
        self.src = os.path.join(self.dir, "src.wav")
        with wave.open(self.src, "wb") as wf:
            wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(44100)
            stereo = np.repeat(tone(440, 44100, amp=8000)[:, None], 2, axis=1)
            wf.writeframes(stereo.tobytes())
        self.lib = SoundLibrary(os.path.join(self.dir, "lib"))

    def test_add_normalizes_and_persists_outside_temp(self):
        sound, truncated = self.lib.add(self.src, "Труба", "🎺")
        self.assertFalse(truncated)
        pcm = self.lib.pcm(sound.id)
        self.assertAlmostEqual(len(pcm), SR, delta=5)           # 44.1k стерео → 48k моно, 1 секунда
        again = SoundLibrary(self.lib.dir)
        self.assertEqual([s.name for s in again.sounds], ["Труба"])
        self.assertTrue(again.sounds[0].pinned)

    def test_long_sound_is_truncated(self):
        long_src = os.path.join(self.dir, "long.wav")
        with wave.open(long_src, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
            wf.writeframes(tone(300, SR * 25).tobytes())
        sound, truncated = self.lib.add(long_src, "Длинный")
        self.assertTrue(truncated)
        self.assertEqual(len(self.lib.pcm(sound.id)), SR * 20)

    def test_remove_and_garbage(self):
        sound, _ = self.lib.add(self.src, "x")
        self.lib.remove(sound.id)
        self.assertEqual(SoundLibrary(self.lib.dir).sounds, [])
        bad = os.path.join(self.dir, "bad.wav")
        with open(bad, "wb") as fh:
            fh.write(b"not audio at all" * 10)
        with self.assertRaises(ValueError):
            self.lib.add(bad, "bad")

    def test_mp3_via_ffmpeg_fallback(self):
        import subprocess, imageio_ffmpeg
        mp3 = os.path.join(self.dir, "a.mp3")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", self.src, mp3], check=True)
        pcm, _ = decode_audio_file(mp3)
        self.assertGreater(len(pcm), SR * 0.9)

    def test_player_streams_frames_in_real_time_and_can_stop(self):
        sent, local = [], []
        player = SoundPlayer(sent.append, local.append)
        pcm = tone(440, FRAME * 25)                              # 0.5 с
        t0 = time.monotonic()
        player.play("a", pcm)
        player._thread.join(3)
        took = time.monotonic() - t0
        self.assertEqual(len(sent), 25)
        self.assertEqual(len(local), 25)
        self.assertGreater(took, 0.35)                            # идёт в реальном времени, а не залпом
        self.assertLess(took, 0.7)
        sent.clear()
        player.play("b", tone(440, FRAME * 200))
        time.sleep(0.1)
        player.stop()
        self.assertFalse(player.playing)
        self.assertLess(len(sent), 15)

    def test_player_local_only(self):
        sent, local = [], []
        player = SoundPlayer(sent.append, local.append)
        player.play("a", tone(440, FRAME * 3), broadcast=False)
        player._thread.join(2)
        self.assertEqual(sent, [])
        self.assertEqual(len(local), 3)


if __name__ == "__main__":
    unittest.main()
