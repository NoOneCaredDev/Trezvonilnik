from __future__ import annotations
import importlib
import logging
import threading

import numpy as np

from media.audio.codec import VoiceDecoder, VoiceEncoder
from media.audio.dsp import EchoSuppressor, NoiseGate, NoiseSuppressor
from media.audio.mixer import AudioMixer, rms_db, SILENCE_DB

SAMPLE_RATE = 48000
FRAME_MS = 20
FRAME = SAMPLE_RATE * FRAME_MS // 1000


def list_devices() -> tuple[list[tuple[int, str]], list[tuple[int, str]], str | None]:
    """(входы, выходы, ошибка). Без PortAudio вернёт пустые списки и текст ошибки."""
    try:
        sd = importlib.import_module("sounddevice")
        inputs, outputs = [], []
        for index, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                inputs.append((index, dev["name"]))
            if dev.get("max_output_channels", 0) > 0:
                outputs.append((index, dev["name"]))
        return inputs, outputs, None
    except Exception as exc:
        return [], [], str(exc)


class AudioEngine:
    """Захват → (усиление → шумодав → эхоподавление → гейт → эффекты/плагины) → Opus → сеть;
    сеть → декодер ПОД КАЖДОГО говорящего → микшер → колонки.

    Вывод сделан через callback PortAudio: он сам задаёт темп. Раньше блокирующий write()
    плюс sleep() рассинхронизировали цикл с аудиоустройством и давали щелчки."""

    def __init__(self, send_voice, settings, processor_chain=None, voice_changer=None):
        self.send_voice = send_voice
        self.settings = settings
        self.processor_chain = processor_chain
        self.voice_changer = voice_changer
        self.mixer = AudioMixer(SAMPLE_RATE)
        self.encoder = VoiceEncoder(SAMPLE_RATE, FRAME_MS, "voip", bitrate=40_000)
        self.decoders: dict[tuple[int, str], VoiceDecoder] = {}
        self.ns = NoiseSuppressor(FRAME, settings.ns_strength / 100)
        self.gate = NoiseGate(settings.gate_threshold_db)
        self.echo = EchoSuppressor()
        self.muted = False
        self.deafened = False
        self.monitor = False            # слышать себя (проверка эффектов; лучше в наушниках)
        self.running = False
        self.error: str | None = None
        self.input_level_db = SILENCE_DB    # уровень после обработки, используемый индикатором
        self.input_raw_level_db = SILENCE_DB  # сырой уровень непосредственно с устройства
        self.input_peak = 0
        self.speaking = False
        self._in_buf = np.zeros(0, dtype=np.int16)
        self._streams: list = []
        self._lock = threading.Lock()
        # Диагностика реальных PortAudio callback-ов. Эти счётчики позволяют
        # отличить «поток открыт» от «устройство действительно гоняет PCM».
        self.input_callbacks = 0
        self.output_callbacks = 0
        self.input_status_count = 0
        self.output_status_count = 0
        self.callback_errors = 0
        self.last_input_status = ""
        self.last_output_status = ""
        self.apply_settings()

    @property
    def codec_name(self) -> str:
        return self.encoder.name

    # ------------------------------------------------------------------ настройки
    def apply_settings(self):
        s = self.settings
        self.ns.set_strength(s.ns_strength / 100)
        self.gate.threshold_db = s.gate_threshold_db
        self.mixer.master = s.output_volume / 100
        self.mixer.sfx_volume = s.sfx_volume / 100
        self.mixer.music_volume = s.music_volume / 100
        if self.voice_changer and (self.voice_changer.effect, self.voice_changer.intensity) != (s.voice_effect, s.voice_intensity):
            self.voice_changer.set_effect(s.voice_effect, s.voice_intensity)

    # ------------------------------------------------------------------ жизненный цикл
    def start(self) -> bool:
        if self.running:
            return True
        sd = None
        last_exc = None
        try:
            sd = importlib.import_module("sounddevice")
            s = self.settings
            for input_extra, output_extra in self._extra_settings(sd):
                inp = out = None
                try:
                    inp = sd.InputStream(
                        device=s.mic_index, samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=FRAME, callback=self._capture,
                        extra_settings=input_extra,
                    )
                    out = sd.OutputStream(
                        device=s.output_index, samplerate=SAMPLE_RATE, channels=1,
                        dtype="int16", blocksize=FRAME, callback=self._playback,
                        extra_settings=output_extra,
                    )
                    # Разрешаем callback-ам работать до start(): PortAudio может
                    # вызвать callback немедленно после запуска первого потока.
                    self.running = True
                    inp.start()
                    out.start()
                    self._streams = [inp, out]
                    self.error = None
                    try:
                        input_info = sd.query_devices(s.mic_index, "input")
                    except Exception as info_exc:
                        input_info = f"<не удалось получить сведения: {info_exc}>"
                    try:
                        output_info = sd.query_devices(s.output_index, "output")
                    except Exception as info_exc:
                        output_info = f"<не удалось получить сведения: {info_exc}>"
                    logging.info("Аудио запущено: input_index=%r input=%r output_index=%r output=%r rate=%s frame=%s",
                                 s.mic_index, input_info, s.output_index, output_info, SAMPLE_RATE, FRAME)
                    return True
                except Exception as exc:
                    last_exc = exc
                    self.running = False
                    for stream in (out, inp):
                        if stream is not None:
                            try:
                                stream.stop()
                            except Exception:
                                pass
                            try:
                                stream.close()
                            except Exception:
                                pass
            raise last_exc or RuntimeError("не удалось открыть аудиоустройства")
        except Exception as exc:
            self.running = False
            self.error = str(exc)
            logging.exception("Не удалось запустить аудиодвижок: %s", exc)
            self.close()
            return False

    def diagnostics(self) -> dict:
        """Снимок состояния аудиоустройств и callback-ов для окна диагностики."""
        return {
            "running": self.running,
            "error": self.error,
            "codec": self.codec_name,
            "input_callbacks": self.input_callbacks,
            "output_callbacks": self.output_callbacks,
            "input_status_count": self.input_status_count,
            "output_status_count": self.output_status_count,
            "callback_errors": self.callback_errors,
            "last_input_status": self.last_input_status,
            "last_output_status": self.last_output_status,
            "input_level_db": self.input_level_db,
            "input_raw_level_db": self.input_raw_level_db,
            "input_peak": self.input_peak,
            "output_level_db": self.mixer.out_level_db,
            "queued_channels": len(self.mixer.channels),
        }

    @staticmethod
    def _extra_settings(sd):
        yield (None, None)
        wasapi = getattr(sd, "WasapiSettings", None)
        if wasapi:                           # WASAPI в общем режиме не любит чужую частоту — просим конвертировать
            try:
                yield (wasapi(auto_convert=True), wasapi(auto_convert=True))
            except Exception:
                pass

    def restart(self) -> bool:
        self.close()
        return self.start()

    def close(self):
        self.running = False
        for stream in self._streams:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._streams = []

    # ------------------------------------------------------------------ микрофон
    def process_frame(self, frame: np.ndarray):
        """Чистая функция конвейера (без устройств, поэтому тестируется): -> (int16 кадр, говорим ли)."""
        s = self.settings
        x = frame.astype(np.float32)
        if s.mic_gain != 100:
            x = np.clip(x * (s.mic_gain / 100), -32768, 32767)
        if s.noise_suppression:
            x = self.ns.process(x)
        level = rms_db(x)
        if s.echo_suppression:
            x = self.echo.process(x, level, self.mixer.out_level_db)
        if s.gate_enabled:
            x = self.gate.process(x, level)
            is_open = self.gate.is_open
        else:
            is_open = level > -60.0
        self.input_level_db = level
        out = np.clip(x, -32768, 32767).astype(np.int16)
        if self.processor_chain:
            out = self.processor_chain.process(out, {"sample_rate": SAMPLE_RATE})
        return out, is_open

    def _capture(self, indata, frames, time_info, status):
        self.input_callbacks += 1
        if status:
            self.input_status_count += 1
            self.last_input_status = str(status)
            logging.warning("PortAudio input status: %s", status)
        if not self.running:
            return
        try:
            raw = np.asarray(indata[:, 0], dtype=np.int16)
            self.input_raw_level_db = rms_db(raw)
            self.input_peak = int(np.max(np.abs(raw.astype(np.int32)))) if raw.size else 0
            if self.input_callbacks <= 3:
                logging.info("Микрофон callback #%d: frames=%d raw_rms=%.1f dBFS peak=%d status=%s",
                             self.input_callbacks, frames, self.input_raw_level_db,
                             self.input_peak, status)
            self._in_buf = np.concatenate((self._in_buf, raw))
            while len(self._in_buf) >= FRAME:
                frame, self._in_buf = self._in_buf[:FRAME], self._in_buf[FRAME:]
                out, is_open = self.process_frame(frame)
                self.speaking = is_open and not self.muted
                if self.monitor:
                    self.mixer.push(0, out, "self")
                if self.speaking and not self.muted:
                    self.send_voice(self.encoder.encode(out))
        except Exception as exc:
            self.callback_errors += 1
            self.error = f"Ошибка захвата/обработки микрофона: {exc}"
            logging.exception(self.error)

    # ------------------------------------------------------------------ приём и вывод
    def receive(self, user_id: int, payload: bytes, kind: str = "voice"):
        dec = self.decoders.get((user_id, kind))
        if dec is None:
            dec = self.decoders[(user_id, kind)] = VoiceDecoder(SAMPLE_RATE, FRAME_MS)
        try:
            samples = dec.decode(payload)
        except Exception:
            return
        if samples is not None:
            self.mixer.push(user_id, samples, kind)

    def receive_sfx(self, user_id: int, payload: bytes):
        self.receive(user_id, payload, "sfx")

    def receive_music(self, payload: bytes):
        self.receive(0, payload, "music")

    def forget(self, user_id: int):
        self.mixer.forget(user_id)
        for key in [k for k in self.decoders if k[0] == user_id]:
            self.decoders.pop(key, None)

    def _playback(self, outdata, frames, time_info, status):
        self.output_callbacks += 1
        if status:
            self.output_status_count += 1
            self.last_output_status = str(status)
            logging.warning("PortAudio output status: %s", status)
        try:
            mixed = self.mixer.mix(frames)
            outdata[:, 0] = 0 if self.deafened else mixed
        except Exception as exc:
            self.callback_errors += 1
            self.error = f"Ошибка воспроизведения: {exc}"
            logging.exception(self.error)
            outdata.fill(0)
