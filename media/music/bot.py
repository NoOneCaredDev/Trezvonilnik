"""Музыкальный бот хоста.

Ссылка (YouTube, SoundCloud, любой сайт, который понимает yt-dlp) → прямой аудиопоток → ffmpeg
декодирует в 48 кГц моно → кадры по 20 мс уходят в комнату пакетами MUSIC и в локальный микшер хоста.
Spotify отдаёт музыку только по DRM, поэтому ссылка на трек превращается в «исполнитель + название»
и ищется на YouTube — как делают все музыкальные боты.
Бот работает на машине хоста: интернет и ffmpeg нужны только ему.
"""
from __future__ import annotations
import html
import logging
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import numpy as np

from media.audio.codec import VoiceEncoder

RATE = 48000
FRAME = 960
MAX_DURATION = 3 * 3600
MAX_QUEUE = 30


@dataclass
class Track:
    title: str
    artist: str = ""
    duration: float = 0.0
    stream_url: str = ""
    headers: dict = field(default_factory=dict)
    requested_by: str = ""
    source: str = ""

    def brief(self) -> dict:
        return {"title": self.title, "artist": self.artist, "duration": self.duration, "by": self.requested_by}


def ffmpeg_path() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def classify(query: str) -> str:
    q = query.strip()
    if re.match(r"^https?://", q, re.I):
        host = urllib.parse.urlparse(q).netloc.lower()
        if host.endswith("spotify.com") or host == "spotify.link":
            return "spotify"
        return "url"
    return "search"


def parse_spotify_meta(page: str) -> tuple[str, str]:
    """(название, исполнитель) из og-тегов страницы трека."""
    def meta(prop):
        m = re.search(r'<meta[^>]+property="og:%s"[^>]+content="([^"]*)"' % prop, page) or \
            re.search(r'<meta[^>]+content="([^"]*)"[^>]+property="og:%s"' % prop, page)
        return html.unescape(m.group(1)).strip() if m else ""
    title, desc = meta("title"), meta("description")
    artist = ""
    parts = [p.strip() for p in desc.split("·")]
    if len(parts) >= 2:
        artist = re.sub(r"^.*?on Spotify\.\s*", "", parts[0]).strip()
        if artist.lower() == title.lower() and len(parts) > 1:
            artist = parts[1]
    return title, artist


class TrackResolver:
    def __init__(self, fetch=None, ytdlp_factory=None):
        self._fetch = fetch or self._http_get
        self._ytdlp_factory = ytdlp_factory

    @staticmethod
    def _http_get(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read(400_000).decode("utf-8", "replace")

    def resolve(self, query: str, requested_by: str = "") -> Track:
        kind, q = classify(query), query.strip()
        source = "YouTube"
        if kind == "spotify":
            title, artist = parse_spotify_meta(self._fetch(q))
            if not title:
                raise ValueError("Не удалось прочитать ссылку Spotify (поддерживаются ссылки на отдельные треки)")
            q, source = f"ytsearch1:{artist} {title} audio".strip(), "Spotify → YouTube"
        elif kind == "search":
            q = f"ytsearch1:{q}"
        info = self._extract(q)
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            if not entries:
                raise ValueError("Ничего не найдено")
            info = entries[0]
        if not info.get("url"):
            raise ValueError("Не удалось получить аудиопоток")
        duration = float(info.get("duration") or 0)
        if duration > MAX_DURATION:
            raise ValueError("Слишком длинный трек (максимум 3 часа)")
        host = urllib.parse.urlparse(query.strip()).netloc.lower()
        if kind == "url":
            source = "SoundCloud" if "soundcloud" in host else (info.get("extractor_key") or "Web")
        return Track(title=info.get("title") or "Без названия",
                     artist=info.get("uploader") or info.get("artist") or "",
                     duration=duration, stream_url=info["url"],
                     headers=dict(info.get("http_headers") or {}),
                     requested_by=requested_by, source=source)

    def _extract(self, q: str) -> dict:
        if self._ytdlp_factory:
            ydl = self._ytdlp_factory()
        else:
            try:
                import yt_dlp
            except ImportError as exc:
                raise ValueError("Не установлен yt-dlp (pip install yt-dlp)") from exc
            ydl = yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "format": "bestaudio/best",
                                    "noplaylist": True, "socket_timeout": 15, "skip_download": True})
        with ydl:
            return ydl.extract_info(q, download=False)


class MusicBot:
    def __init__(self, send_frame, push_local, on_state=None, on_message=None, resolver=None):
        self.send_frame = send_frame
        self.push_local = push_local
        self.on_state = on_state
        self.on_message = on_message
        self.resolver = resolver or TrackResolver()
        self.encoder = VoiceEncoder(RATE, 20, "audio", bitrate=96_000)
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.position = 0.0
        self.paused = False
        self.resolving = 0
        self._skip = threading.Event()
        self._closed = threading.Event()
        self._cond = threading.Condition()
        self._proc: subprocess.Popen | None = None
        self._thread = threading.Thread(target=self._loop, name="music-bot", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ команды
    def add(self, query: str, requested_by: str = ""):
        query = query.strip()
        if not query:
            return
        if len(self.queue) >= MAX_QUEUE:
            self._say("Очередь заполнена")
            return
        self.resolving += 1
        self._emit()

        def work():
            try:
                track = self.resolver.resolve(query, requested_by)
            except Exception as exc:
                logging.warning("Музыка: не удалось разобрать %r: %s", query, exc)
                self._say(f"Не получилось добавить: {exc}"[:200])
                track = None
            finally:
                self.resolving -= 1
            if track:
                with self._cond:
                    self.queue.append(track)
                    self._cond.notify_all()
            self._emit()
        threading.Thread(target=work, name="music-resolve", daemon=True).start()

    def skip(self):
        self._skip.set()
        self.paused = False
        self._kill()

    def toggle_pause(self):
        self.paused = not self.paused
        self._emit()

    def stop(self):
        with self._cond:
            self.queue.clear()
        self.skip()

    def remove(self, index: int):
        with self._cond:
            if 0 <= index < len(self.queue):
                self.queue.pop(index)
        self._emit()

    def close(self):
        self._closed.set()
        self._skip.set()
        self._kill()
        with self._cond:
            self._cond.notify_all()

    def handle_command(self, msg: dict):
        """Команда от любого участника (сервер пересылает её хосту)."""
        action = msg.get("action")
        who = msg.get("nick", "")
        if action == "add":
            self.add(str(msg.get("url", "")), who)
        elif action == "skip":
            self.skip()
        elif action == "pause":
            self.toggle_pause()
        elif action == "stop":
            self.stop()
        elif action == "remove":
            try:
                self.remove(int(msg.get("index", -1)))
            except (TypeError, ValueError):
                pass

    def state(self) -> dict:
        return {"cmd": "music_state",
                "now": self.current.brief() if self.current else None,
                "pos": round(self.position, 1), "paused": self.paused,
                "queue": [t.brief() for t in self.queue], "resolving": self.resolving}

    # ------------------------------------------------------------------ внутреннее
    def _say(self, text):
        if self.on_message:
            self.on_message(text)

    def _emit(self):
        if self.on_state:
            self.on_state(self.state())

    def _kill(self):
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def _loop(self):
        while not self._closed.is_set():
            with self._cond:
                while not self.queue and not self._closed.is_set():
                    self._cond.wait(0.5)
                if self._closed.is_set():
                    return
                track = self.queue.pop(0)
            self.current, self.position, self._skip = track, 0.0, threading.Event()
            self._say(f"Играет: {track.artist + ' — ' if track.artist else ''}{track.title}")
            self._emit()
            try:
                self._play(track)
            except Exception as exc:
                logging.exception("Ошибка воспроизведения")
                self._say(f"Ошибка воспроизведения: {exc}"[:200])
            self.current, self.position = None, 0.0
            self._emit()

    def _command(self, track: Track) -> list[str]:
        ff = ffmpeg_path()
        if not ff:
            raise RuntimeError("не найден ffmpeg (pip install imageio-ffmpeg)")
        cmd = [ff, "-nostdin", "-loglevel", "error"]
        if track.stream_url.startswith("http"):
            cmd += ["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "4"]
            if track.headers:
                cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in track.headers.items())]
        return cmd + ["-i", track.stream_url, "-vn", "-f", "s16le", "-ar", str(RATE), "-ac", "1", "pipe:1"]

    def _play(self, track: Track):
        self._proc = proc = subprocess.Popen(self._command(track), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                             stdin=subprocess.DEVNULL)
        frames, t0, last_emit, got_data = 0, time.monotonic(), 0.0, False
        try:
            while not self._skip.is_set() and not self._closed.is_set():
                if self.paused:
                    self._skip.wait(0.1)
                    t0 = time.monotonic() - frames * FRAME / RATE      # пауза не должна «догонять» время
                    continue
                raw = self._read_exact(proc.stdout, FRAME * 2)
                if len(raw) < FRAME * 2:
                    if len(raw) and got_data:
                        raw = raw + bytes(FRAME * 2 - len(raw))
                    else:
                        break
                got_data = True
                frame = np.frombuffer(raw, dtype=np.int16)
                self.push_local(frame)
                try:
                    self.send_frame(self.encoder.encode(frame))
                except Exception:
                    pass
                frames += 1
                self.position = frames * FRAME / RATE
                ahead = t0 + frames * FRAME / RATE - time.monotonic() - 0.08     # держим 80 мс «в запас»
                if ahead > 0:
                    self._skip.wait(ahead)
                now = time.monotonic()
                if now - last_emit >= 1.0:
                    last_emit = now
                    self._emit()
        finally:
            self._kill()
            err = b""
            try:
                err = proc.stderr.read(400)
                proc.wait(timeout=2)
            except Exception:
                pass
            for pipe in (proc.stdout, proc.stderr):      # иначе на каждый трек утекает по два дескриптора
                try:
                    pipe.close()
                except Exception:
                    pass
            if not got_data and not self._skip.is_set() and not self._closed.is_set():
                self._say("Не удалось воспроизвести трек" + (f": {err.decode('utf-8', 'replace').strip()[:120]}" if err else ""))

    @staticmethod
    def _read_exact(stream, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = stream.read(n - len(buf))
            if not chunk:
                break
            buf += chunk
        return buf
