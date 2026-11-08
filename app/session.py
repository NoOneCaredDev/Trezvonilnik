"""CallSession — вся логика звонка без единой строчки интерфейса.

Окно только подписывается на сигналы и вызывает методы. Поэтому логику можно тестировать без GUI,
а интерфейс — переделывать, не трогая сеть и звук."""
from __future__ import annotations
import copy
import dataclasses
import logging
import os

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

from config.settings import AppSettings, SettingsStore, STREAM_PRESETS
from media.audio.effects import VoiceChanger
from media.audio.engine import AudioEngine
from media.audio.mixer import SILENCE_DB
from media.audio.soundboard import SoundLibrary, SoundPlayer
from media.music.bot import MusicBot
from media.video.capture import CaptureSource
from media.video.receiver import StreamReceiver
from media.video.streamer import VideoStreamer
from network.client import RoomClient
from network.server import RoomServer
from plugins.chain import AudioProcessorChain
from services.avatars import AvatarStore, process_avatar
from services.monitor import NetworkStats

SPEAKING_DB = -50.0


class SessionError(Exception):
    pass


class CallSession(QObject):
    users_updated = Signal(list)
    toast = Signal(str, str)                 # текст, вид (info/ok/warn/error)
    reaction = Signal(int, str)
    wheel_remote = Signal(dict, str)
    music_state = Signal(dict)
    music_notice = Signal(str)
    stream_frame = Signal(QImage)
    streams_changed = Signal()
    my_stream_changed = Signal(bool)
    watchers_changed = Signal(int)
    avatars_changed = Signal()
    connection = Signal(str, str)            # состояние, текст
    kicked_out = Signal()
    sounds_changed = Signal()
    playing_sound = Signal(object)
    my_state_changed = Signal()
    restrictions_changed = Signal()
    room_named = Signal(str)
    audio_error = Signal(str)
    _stream_ended = Signal(str)
    _bot_state = Signal(dict)
    _bot_msg = Signal(str)
    _sound_done = Signal(object)

    def __init__(self, nickname: str, host: bool, host_ip: str, password: str, settings: AppSettings,
                 store: SettingsStore | None = None, plugin_manager=None, room_name: str = ""):
        super().__init__()
        self.nickname, self.is_host = nickname, host
        self.settings, self.store = settings, store
        self.plugins = plugin_manager
        self.stats = NetworkStats()
        try:
            self.server = RoomServer(password, settings.network_port, room_name=room_name) if host else None
        except OSError as exc:
            raise SessionError(f"Не удалось занять UDP-порт {settings.network_port}: {exc}. "
                               "Возможно, комната уже запущена в другом окне.") from exc
        self.client = RoomClient(nickname, "127.0.0.1" if host else host_ip, password, settings.network_port, self.stats)
        self.voice_changer = VoiceChanger(settings.voice_effect, settings.voice_intensity)
        processors = [self.voice_changer] + list(getattr(plugin_manager, "audio_processors", []) or [])
        self.engine = AudioEngine(self.client.send_audio, settings, AudioProcessorChain(processors), self.voice_changer)
        self.library = SoundLibrary()
        self.player = SoundPlayer(self.client.send_sfx, lambda f: self.engine.mixer.push(0, f, "self"),
                                  on_finished=lambda sid: self._sound_done.emit(sid))
        # TTS использует тот же сетевой канал SFX, но отдельный проигрыватель,
        # чтобы озвучка не обрывала звук, запущенный через саундпад.
        self.tts_player = SoundPlayer(self.client.send_sfx, lambda f: self.engine.mixer.push(0, f, "self"))
        self.bot: MusicBot | None = None
        if host:
            self.bot = MusicBot(self.client.send_music, lambda f: self.engine.mixer.push(0, f, "music"),
                                on_state=lambda st: self._bot_state.emit(st),
                                on_message=lambda m: self._bot_msg.emit(m))
        self.avatar_store = AvatarStore()
        self.avatar_data: dict[int, bytes] = {}
        self._avatar_hash: dict[int, str] = {}
        self._avatar_tries: dict[int, int] = {}
        self._local_avatar_cache: dict[str, bytes] = {}
        self.receiver = StreamReceiver()
        self.streamer: VideoStreamer | None = None
        self.watching: int | None = None
        self.watchers = 0
        self.users: list[dict] = []
        self.room_name = room_name
        self.music = {"now": None, "queue": [], "paused": False, "pos": 0, "resolving": 0}
        self._first_list = True
        self._was_online = False
        self._pre_deafen_muted = False
        self._closed = False

        c = self.client
        c.on_audio = self.engine.receive
        c.on_sfx = self.engine.receive_sfx
        c.on_music = self.engine.receive_music
        c.on_video = self.receiver.push
        c.users_changed.connect(self._on_users)
        c.control_received.connect(self._on_control)
        c.connection_state.connect(self._on_connection)
        c.avatar_received.connect(self._on_avatar_blob)
        c.kicked.connect(self.kicked_out)
        c.server_error.connect(lambda m: self.toast.emit(m, "error"))
        c.room_named.connect(self._on_room_named)
        self.receiver.frame.connect(self.stream_frame)
        self._stream_ended.connect(self._on_stream_ended)
        self._bot_state.connect(self._on_bot_state)
        self._bot_msg.connect(self._on_bot_msg)
        self._sound_done.connect(lambda sid: self.playing_sound.emit(None))

    # ------------------------------------------------------------------ запуск / остановка
    def start(self):
        if self.server:
            self.server.start()
        self.client.start()
        if not self.engine.start():
            self.audio_error.emit(self.engine.error or "аудиоустройства недоступны")

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.client.leave()
        except Exception:
            pass
        if self.bot:
            self.bot.close()
        self.player.stop()
        self.tts_player.stop()
        if self.streamer:
            self.streamer.stop()
        self.receiver.close()
        self.engine.close()
        self.client.close()
        if self.server:
            self.server.close()
        if self.plugins:
            self.plugins.unload()

    @property
    def my_id(self) -> int:
        return self.client.user_id

    def me(self) -> dict:
        return next((u for u in self.users if u["id"] == self.my_id), {})

    def user(self, uid: int) -> dict | None:
        return next((u for u in self.users if u["id"] == uid), None)

    # ------------------------------------------------------------------ соединение
    def _on_connection(self, state: str, *_):
        texts = {"connecting": "Подключение…", "online": "Подключено", "reconnecting": "Связь потеряна, переподключаемся…",
                 "failed": "Нет ответа от хоста. Проверьте IP, пароль комнаты и что у хоста открыт UDP-порт."}
        self.connection.emit(state, texts.get(state, state))
        if state == "online":
            if self._was_online:
                self.toast.emit("Соединение восстановлено", "ok")
            self._was_online = True
            self._announce_self()
        elif state == "reconnecting":
            self.toast.emit("Связь с хостом потеряна", "warn")

    def _on_room_named(self, name: str):
        self.room_name = name
        self.room_named.emit(name)

    def _announce_self(self):
        """После входа и после переподключения серверу надо заново рассказать, кто мы."""
        self._send_state()
        if self.settings.avatar_source and os.path.exists(self.settings.avatar_source):
            data = self.avatar_store.get(self._avatar_hash.get(self.my_id, "")) if self.my_id in self._avatar_hash else None
            try:
                data = data or process_avatar(self.settings.avatar_source)[0]
                self._publish_avatar(data)
            except Exception:
                logging.exception("Не удалось отправить аватарку")
        if self.streamer and self.streamer._thread and self.streamer._thread.is_alive():
            self.client.send_control({"cmd": "stream", "on": True, "title": self.streamer.source.title})
        if self.watching not in (None, self.my_id):
            self.client.send_control({"cmd": "watch", "target": self.watching, "on": True})

    def _send_state(self):
        self.client.send_control({"cmd": "state", "muted": self.engine.muted, "deafened": self.engine.deafened})

    # ------------------------------------------------------------------ участники
    def _on_users(self, users: list):
        old = {u["id"]: u for u in self.users}
        new = {u["id"]: u for u in users}
        me = self.my_id
        if not self._first_list:
            for uid, u in new.items():
                if uid not in old and uid != me:
                    self.toast.emit(f"{u['nickname']} зашёл(ла) в комнату", "info")
                elif uid in old and uid != me:
                    if u.get("sharing") and not old[uid].get("sharing"):
                        self.toast.emit(f"{u['nickname']} начал(а) трансляцию", "info")
            for uid, u in old.items():
                if uid not in new and uid != me:
                    self.toast.emit(f"{u['nickname']} вышел(ла)", "info")
        before = old.get(me, {})
        after = new.get(me, {})
        for key, text in (("mic_locked", "микрофон"), ("sfx_locked", "саундпад"), ("stream_locked", "трансляции")):
            if after.get(key) != before.get(key) and before:
                self.toast.emit(f"Хост {'запретил вам' if after.get(key) else 'вернул вам'}: {text}", "warn" if after.get(key) else "ok")
        self._first_list = False
        for uid in set(old) - set(new):
            self.engine.forget(uid)
            self.avatar_data.pop(uid, None)
            self._avatar_hash.pop(uid, None)
            if self.watching == uid:
                self.unwatch()
        self.users = list(users)
        if self.bot and any(uid not in old and uid != me for uid in new):
            self._broadcast_music()                                  # новичок сразу видит, что играет
        self._sync_avatars()
        self.users_updated.emit(self.users)
        self.streams_changed.emit()
        if after != before:
            self.restrictions_changed.emit()
            self.my_state_changed.emit()

    # ------------------------------------------------------------------ управление собой
    def set_muted(self, muted: bool):
        if self.me().get("mic_locked") and not muted:
            self.toast.emit("Хост отключил вам микрофон", "warn")
            return
        self.engine.muted = muted
        self._send_state()
        self.my_state_changed.emit()

    def set_deafened(self, deaf: bool):
        """Как в Discord: «оглохнуть» заодно выключает микрофон, а при возврате — возвращает как было."""
        if deaf:
            self._pre_deafen_muted = self.engine.muted
            self.engine.muted = True
        else:
            self.engine.muted = self._pre_deafen_muted
        self.engine.deafened = deaf
        self._send_state()
        self.my_state_changed.emit()

    # ------------------------------------------------------------------ локальные настройки людей
    def set_user_volume(self, uid: int, percent: int):
        self.engine.mixer.set_volume(uid, percent)

    def mute_user(self, uid: int, on: bool):
        self.engine.mixer.set_muted(uid, on)

    def mute_user_sfx(self, uid: int, on: bool):
        self.engine.mixer.set_sfx_muted(uid, on)

    def user_local(self, uid: int) -> dict:
        m = self.engine.mixer
        return {"volume": m.volume_of(uid), "muted": uid in m.muted, "sfx_muted": uid in m.sfx_muted}

    # ------------------------------------------------------------------ админка (проверяет сервер)
    def admin(self, action: str, uid: int, value: bool = True):
        if self.is_host:
            self.client.send_control({"cmd": "admin", "action": action, "target": uid, "value": value})

    # ------------------------------------------------------------------ реакции, колесо
    def send_reaction(self, emoji: str):
        self.client.send_control({"cmd": "react", "emoji": emoji})

    def send_wheel(self, params: dict):
        self.client.send_control(dict(params, cmd="wheel"))

    def _nick(self, uid: int) -> str:
        u = self.user(uid)
        return u["nickname"] if u else "Кто-то"

    # ------------------------------------------------------------------ команды от сервера
    def _on_control(self, msg: dict):
        cmd = msg.get("cmd")
        if cmd == "react":
            self.reaction.emit(int(msg.get("from", 0)), str(msg.get("emoji", "")))
        elif cmd == "stop_stream":
            self.stop_stream()
            if msg.get("reason"):
                self.toast.emit(str(msg["reason"]), "warn")
        elif cmd == "watchers":
            self.watchers = int(msg.get("count", 0))
            if self.streamer:
                self.streamer.viewers = self.watchers
            self.watchers_changed.emit(self.watchers)
        elif cmd == "wheel":
            who = self._nick(int(msg.get("from", 0)))
            self.wheel_remote.emit(msg, who)
        elif cmd == "music_state":
            self._apply_music(msg)
        elif cmd == "music" and self.bot:
            self.bot.handle_command(dict(msg, nick=self._nick(int(msg.get("from", 0)))))

    # ------------------------------------------------------------------ музыка
    def music_command(self, command: dict):
        if self.bot:
            self.bot.handle_command(dict(command, nick=self.nickname))
        else:
            self.client.send_control(dict(command, cmd="music"))

    def _on_bot_state(self, st: dict):
        self._apply_music(st)
        self.client.send_control(st)

    def _on_bot_msg(self, text: str):
        st = dict(self.bot.state(), msg=text)
        self._apply_music(st)
        self.client.send_control(st)

    def _broadcast_music(self):
        if self.bot:
            self.client.send_control(self.bot.state())

    def _apply_music(self, st: dict):
        self.music = st
        self.music_state.emit(st)
        if st.get("msg"):
            self.music_notice.emit(st["msg"])

    # ------------------------------------------------------------------ саундпад
    def play_tts(self, pcm):
        if self.me().get("sfx_locked"):
            self.toast.emit("Хост запретил вам использовать звуковые эффекты", "warn")
            return False
        self.tts_player.play("tts", pcm, broadcast=True)
        return True

    def play_sound(self, sound_id: str):
        if self.me().get("sfx_locked"):
            self.toast.emit("Хост запретил вам саундпад", "warn")
            return
        sound, pcm = self.library.get(sound_id), self.library.pcm(sound_id)
        if sound is None or pcm is None:
            return
        self.player.play(sound_id, pcm, sound.volume / 100.0, broadcast=True)
        self.playing_sound.emit(sound_id)

    def preview_sound(self, sound_id: str):
        sound, pcm = self.library.get(sound_id), self.library.pcm(sound_id)
        if sound is not None and pcm is not None:
            self.player.play(sound_id, pcm, sound.volume / 100.0, broadcast=False)
            self.playing_sound.emit(sound_id)

    def stop_sound(self):
        self.player.stop()
        self.playing_sound.emit(None)

    def add_sound(self, path: str, name: str, emoji: str, volume: int):
        sound, truncated = self.library.add(path, name, emoji, volume)
        if truncated:
            self.toast.emit("Звук длиннее 20 секунд — он обрезан", "warn")
        self.sounds_changed.emit()
        return sound

    def edit_sound(self, sound_id: str, **changes):
        self.library.update(sound_id, **changes)
        self.sounds_changed.emit()

    def delete_sound(self, sound_id: str):
        if self.player.current == sound_id:
            self.stop_sound()
        self.library.remove(sound_id)
        self.sounds_changed.emit()

    # ------------------------------------------------------------------ демонстрация экрана
    def start_stream(self, source: CaptureSource, preset: str | None = None):
        if self.me().get("stream_locked"):
            self.toast.emit("Хост запретил вам трансляции", "warn")
            return False
        if self.streamer:
            self.stop_stream()
        if preset:
            self.settings.apply_preset(preset)
            self._save_settings()
        s = self.settings
        self.streamer = VideoStreamer(self.client.send_video, source, s.video_fps, s.video_width, s.video_kbps,
                                      on_local_frame=self._local_frame, on_ended=lambda why: self._stream_ended.emit(why))
        self.streamer.viewers = self.watchers
        self.streamer.self_view = self.watching == self.my_id
        self.streamer.start()
        self.client.send_control({"cmd": "stream", "on": True, "title": source.title[:40]})
        self.my_stream_changed.emit(True)
        return True

    def stop_stream(self):
        streamer, self.streamer = self.streamer, None
        if streamer:
            streamer.stop()
            self.client.send_control({"cmd": "stream", "on": False})
            if self.watching == self.my_id:
                self.unwatch()
            self.watchers = 0
            self.my_stream_changed.emit(False)

    def _on_stream_ended(self, why: str):
        if self.streamer:
            self.stop_stream()
            self.toast.emit(f"Трансляция остановлена: {why}", "warn")

    def _local_frame(self, bgr):
        h, w = bgr.shape[:2]
        self.stream_frame.emit(QImage(bgr.data, w, h, bgr.strides[0], QImage.Format_BGR888).copy())

    @property
    def sharing(self) -> bool:
        return self.streamer is not None

    def watch(self, uid: int):
        if self.watching == uid:
            return
        self.unwatch(notify=False)
        self.watching = uid
        if uid == self.my_id:
            if self.streamer:
                self.streamer.self_view = True
        else:
            self.receiver.set_watch(uid)
            self.client.send_control({"cmd": "watch", "target": uid, "on": True})
        self.streams_changed.emit()

    def unwatch(self, notify=True):
        uid, self.watching = self.watching, None
        if uid is None:
            return
        if uid == self.my_id:
            if self.streamer:
                self.streamer.self_view = False
        else:
            self.client.send_control({"cmd": "watch", "target": uid, "on": False})
        self.receiver.set_watch(None)
        if notify:
            self.streams_changed.emit()

    def streams(self) -> list[dict]:
        return [u for u in self.users if u.get("sharing")]

    # ------------------------------------------------------------------ аватарки
    def set_avatar(self, path: str | None):
        if not path:
            self.settings.avatar_source = ""
            self.avatar_data.pop(self.my_id, None)
            self._avatar_hash.pop(self.my_id, None)
            self.client.send_control({"cmd": "avatar_clear"})
        else:
            data, _ = process_avatar(path)
            self.settings.avatar_source = path
            self._publish_avatar(data)
        self._save_settings()
        self.avatars_changed.emit()

    def _publish_avatar(self, data: bytes):
        digest = self.avatar_store.put(data)
        self.avatar_data[self.my_id] = data
        self._avatar_hash[self.my_id] = digest
        self.client.send_avatar(data)
        self.avatars_changed.emit()

    def _sync_avatars(self):
        for u in self.users:
            uid, digest = u["id"], u.get("avatar", "")
            if uid == self.my_id:
                continue
            if not digest:
                if self.avatar_data.pop(uid, None) is not None:
                    self.avatars_changed.emit()
                self._avatar_hash.pop(uid, None)
                continue
            if self._avatar_hash.get(uid) == digest:
                continue
            data = self.avatar_store.get(digest)
            if data:
                self.avatar_data[uid], self._avatar_hash[uid] = data, digest
                self.avatars_changed.emit()
            else:
                self._request_avatar(uid, digest, 0)

    def _request_avatar(self, uid: int, digest: str, attempt: int):
        """UDP теряет пакеты — если аватарка не дошла, просим снова (до 4 раз)."""
        u = self.user(uid)
        if not u or u.get("avatar") != digest or self._avatar_hash.get(uid) == digest or attempt >= 4 or self._closed:
            return
        self.client.request_avatar(uid)
        QTimer.singleShot(2500, lambda: self._request_avatar(uid, digest, attempt + 1))

    def _on_avatar_blob(self, uid: int, data: bytes):
        digest = self.avatar_store.put(data)
        u = self.user(uid)
        if u and u.get("avatar") == digest:
            self.avatar_data[uid], self._avatar_hash[uid] = data, digest
            self.avatars_changed.emit()

    def avatar_for(self, uid: int) -> bytes | None:
        """Что показывать: локальная подмена (видна только мне) важнее настоящей аватарки."""
        u = self.user(uid)
        if u:
            path = self.settings.local_avatars.get(u["nickname"])
            if path and os.path.exists(path):
                if path not in self._local_avatar_cache:
                    try:
                        self._local_avatar_cache[path] = process_avatar(path)[0]
                    except Exception:
                        return self.avatar_data.get(uid)
                return self._local_avatar_cache[path]
        return self.avatar_data.get(uid)

    def set_local_avatar(self, nickname: str, path: str | None):
        if path:
            self.settings.local_avatars[nickname] = path
        else:
            self.settings.local_avatars.pop(nickname, None)
        self._save_settings()
        self.avatars_changed.emit()

    # ------------------------------------------------------------------ индикаторы
    def levels(self) -> dict[int, tuple[bool, float]]:
        out = {}
        for u in self.users:
            uid = u["id"]
            if uid == self.my_id:
                db = self.engine.input_level_db
                speaking = self.engine.speaking and not self.engine.muted
            else:
                db = max(self.engine.mixer.level_db(uid, "voice"), self.engine.mixer.level_db(uid, "sfx"))
                speaking = db > SPEAKING_DB and uid not in self.engine.mixer.muted
            out[uid] = (speaking, max(0.0, min(1.0, (db + 60) / 50)))
        return out

    # ------------------------------------------------------------------ настройки
    def snapshot_settings(self) -> AppSettings:
        return copy.deepcopy(self.settings)

    def restore_settings(self, snap: AppSettings):
        for f in dataclasses.fields(AppSettings):
            setattr(self.settings, f.name, getattr(snap, f.name))
        self.engine.apply_settings()

    def apply_settings(self, previous: AppSettings | None = None):
        """Применяет настройки на лету; устройства требуют перезапуска аудио (это делается здесь же)."""
        self.engine.apply_settings()
        if previous and (previous.mic_index, previous.output_index) != (self.settings.mic_index, self.settings.output_index):
            if not self.engine.restart():
                self.audio_error.emit(self.engine.error or "не удалось открыть устройство")
        self._save_settings()

    def _save_settings(self):
        if self.store:
            try:
                self.store.save(self.settings)
            except OSError:
                logging.exception("Не удалось сохранить настройки")

    def net_snapshot(self) -> dict:
        return self.stats.snapshot()
