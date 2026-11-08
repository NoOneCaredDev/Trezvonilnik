import unittest
import numpy as np

from media.audio.codec import VoiceEncoder, VoiceDecoder, opus_available
from media.audio.dsp import NoiseGate, NoiseSuppressor, EchoSuppressor
from media.audio.effects import VoiceChanger, EFFECTS
from media.audio.mixer import AudioMixer, Channel, rms_db

SR, N = 48000, 960


def sine(freq, frames=1, amp=8000, start=0):
    t = (np.arange(frames * N) + start) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16)


def peak_freq(x):
    spec = np.abs(np.fft.rfft(x.astype(np.float32) * np.hanning(len(x))))
    return np.argmax(spec) * SR / len(x)


class CodecTests(unittest.TestCase):
    def test_pcm_roundtrip_and_tag(self):
        enc = VoiceEncoder(prefer_opus=False)
        pcm = sine(440)
        payload = enc.encode(pcm)
        self.assertEqual(payload[0], 0)
        np.testing.assert_array_equal(VoiceDecoder().decode(payload), pcm)

    @unittest.skipUnless(opus_available(), "libopus недоступен")
    def test_opus_roundtrip_has_own_decoder_per_stream(self):
        enc = VoiceEncoder(application="voip")
        a, b = VoiceDecoder(), VoiceDecoder()
        for i in range(10):
            out_a = a.decode(enc.encode(sine(440, start=i * N)))
            out_b = b.decode(VoiceEncoder(application="audio").encode(sine(880, start=i * N)))
        self.assertEqual(len(out_a), N)
        self.assertAlmostEqual(peak_freq(out_a), 440, delta=60)
        self.assertAlmostEqual(peak_freq(out_b), 880, delta=60)

    def test_garbage_is_ignored(self):
        self.assertIsNone(VoiceDecoder().decode(b"\x01"))
        self.assertIsNone(VoiceDecoder().decode(b"\x07abc"))


class MixerTests(unittest.TestCase):
    def test_jitter_buffer_waits_for_prefill_then_plays(self):
        m = AudioMixer(prefill_ms=40)
        m.push(1, sine(440))
        self.assertFalse(m.mix(N).any())               # 20 мс < 40 мс — ещё копим
        m.push(1, sine(440))
        self.assertTrue(m.mix(N).any())

    def test_underrun_reprimes(self):
        ch = Channel(prefill=N * 2, max_buffer=N * 10)
        ch.push(sine(440, 3))
        self.assertIsNotNone(ch.pull(N * 3))
        out = ch.pull(N)
        self.assertTrue(out is not None and not out.any())
        ch.push(sine(440))
        self.assertIsNone(ch.pull(N))                  # снова ждёт prefill

    def test_latency_is_bounded(self):
        ch = Channel(prefill=N, max_buffer=N * 5)
        for _ in range(40):
            ch.push(sine(440))
        self.assertLessEqual(ch.buffered, N * 5)

    def test_per_user_volume_mute_and_sfx_mute(self):
        m = AudioMixer(prefill_ms=0)
        m.push(1, sine(440, amp=10000)); m.push(2, sine(440, amp=10000), "sfx")
        base = m.mix(N)
        m.set_muted(1, True); m.set_sfx_muted(2, True)
        m.push(1, sine(440)); m.push(2, sine(440), "sfx")
        self.assertFalse(m.mix(N).any())
        m.set_muted(1, False); m.set_volume(1, 50)
        m.push(1, sine(440, amp=10000))
        half = m.mix(N)
        self.assertAlmostEqual(rms_db(half), rms_db(sine(440, amp=5000)), delta=0.5)
        self.assertTrue(base.any())

    def test_levels_decay_for_speaking_indicator(self):
        m = AudioMixer(prefill_ms=0)
        m.push(7, sine(440))
        self.assertGreater(m.level_db(7), -30)
        m.channels[(7, "voice")].last_push -= 1
        self.assertLess(m.level_db(7), -90)

    def test_no_clipping_wraparound(self):
        m = AudioMixer(prefill_ms=0)
        for uid in range(5):
            m.push(uid, np.full(N, 30000, dtype=np.int16))
        self.assertTrue((m.mix(N) == 32767).all())


class DspTests(unittest.TestCase):
    def test_gate_opens_holds_and_closes_without_clicks(self):
        g = NoiseGate(threshold_db=-40, hold_frames=3)
        quiet = sine(300, amp=20).astype(np.float32)
        loud = sine(300, amp=8000).astype(np.float32)
        self.assertFalse(g.process(quiet).any())
        out = g.process(loud)
        self.assertTrue(g.is_open and abs(out[0]) < 50)          # плавное открытие
        for _ in range(3):
            g.process(quiet)
        self.assertFalse(g.is_open)

    def test_noise_suppressor_kills_stationary_noise_keeps_voice(self):
        rng = np.random.default_rng(1)
        ns = NoiseSuppressor(N, 0.7)
        noise = lambda: rng.normal(0, 400, N).astype(np.float32)
        for _ in range(100):
            ns.process(noise())                                 # прогрев: оценка шума
        before = np.mean([rms_db(noise()) for _ in range(20)])
        after_noise = np.mean([rms_db(ns.process(noise())) for _ in range(20)])
        self.assertLess(after_noise, before - 10)
        tone_in = [sine(1000, amp=8000, start=i * N).astype(np.float32) + noise() for i in range(30)]
        tone_out = [ns.process(f) for f in tone_in]
        self.assertGreater(rms_db(np.concatenate(tone_out[10:])), rms_db(np.concatenate(tone_in[10:])) - 2.5)

    def test_noise_suppressor_is_transparent_in_length_and_finite(self):
        ns = NoiseSuppressor(N, 1.0)
        for i in range(50):
            out = ns.process(sine(500, start=i * N).astype(np.float32))
            self.assertEqual(len(out), N)
            self.assertTrue(np.isfinite(out).all())

    def test_echo_suppressor_ducks_only_when_far_end_is_loud(self):
        e = EchoSuppressor()
        x = np.ones(N, dtype=np.float32) * 1000
        for _ in range(3):
            y = e.process(x, near_db=-40, far_db=-30)
        self.assertLess(y.max(), 200)                              # эхо задавлено
        for _ in range(3):
            y = e.process(x, near_db=-10, far_db=-30)
        self.assertGreater(y.max(), 900)                           # собеседника перебиваем — говорим
        for _ in range(3):
            y = e.process(x, near_db=-40, far_db=-90)
        self.assertGreater(y.max(), 900)                           # колонки молчат


class EffectTests(unittest.TestCase):
    def run_effect(self, name, freq=440, frames=40, intensity=50):
        vc = VoiceChanger(name, intensity)
        out = np.concatenate([vc.process(sine(freq, start=i * N)) for i in range(frames)])
        return out[N * 8:]                                          # без переходного процесса

    def test_none_is_passthrough(self):
        x = sine(440)
        self.assertIs(VoiceChanger("none").process(x), x)

    def test_chipmunk_raises_pitch(self):
        self.assertGreater(peak_freq(self.run_effect("chipmunk")), 440 * 1.3)

    def test_deep_lowers_pitch(self):
        self.assertLess(peak_freq(self.run_effect("deep")), 440 * 0.85)

    def test_pitch_shift_is_accurate(self):
        from media.audio.effects import PitchShifter
        ps = PitchShifter(5)
        out = np.concatenate([ps.process(sine(440, start=i * N).astype(np.float32)) for i in range(40)])[N * 8:]
        self.assertAlmostEqual(peak_freq(out), 440 * 2 ** (5 / 12), delta=15)

    def test_every_effect_is_stable_across_block_sizes_and_never_overflows(self):
        rng = np.random.default_rng(3)
        for name in EFFECTS:
            vc = VoiceChanger(name, 100)
            for _ in range(30):
                n = int(rng.choice([480, 960, 1920]))
                out = vc.process((rng.normal(0, 9000, n)).astype(np.int16))
                self.assertEqual(len(out), n, name)
                self.assertEqual(out.dtype, np.int16)

    def test_switching_effect_midstream(self):
        vc = VoiceChanger("robot")
        vc.process(sine(300))
        vc.set_effect("echo", 80)
        self.assertEqual(len(vc.process(sine(300))), N)


if __name__ == "__main__":
    unittest.main()
