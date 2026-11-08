from __future__ import annotations
import os

from PySide6.QtCore import QEasingCurve, QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from app.netinfo import local_ipv4
from ui import theme, tween
from ui.dialogs.settings_dialog import SettingsDialog
from ui.dialogs.source_picker import SourcePicker
from ui.dialogs.tts_dialog import TTSDialog
from ui.theme import C, mix, qc
from ui.widgets.avatar import AvatarWidget
from ui.widgets.base import Card, IconButton, PillButton, RoundButton, _prop
from ui.widgets.music_panel import MusicPanel
from ui.widgets.popover import UserPopover
from ui.widgets.reactions import ReactionBar, ReactionOverlay
from ui.widgets.soundpad import COLLAPSED_H, EXPANDED_H, SoundDialog, SoundPad
from ui.widgets.stream_stage import StreamStage, StreamWindow
from ui.widgets.toast import ToastHost
from ui.widgets.user_card import ParticipantList
from ui.widgets.wheel import WheelPage
from ui.winutil import enable_dark_titlebar

STATE_COLORS = {"online": "ok", "connecting": "warn", "reconnecting": "warn", "failed": "danger"}


class StatusDot(QWidget):
    pulse = _prop("pulse")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(12, 12)
        self._pulse = 0.0
        self.color = "warn"
        self.busy = True
        self._loop()

    def set_state(self, state: str):
        self.color = STATE_COLORS.get(state, "warn")
        self.busy = state in ("connecting", "reconnecting")
        self.update()

    def _loop(self):
        if self.busy and self.isVisible():
            tween.tween(self, "pulse", 1.0 if self._pulse < 0.5 else 0.0, 700, QEasingCurve.InOutSine, on_done=self._loop)
        else:
            QTimer.singleShot(400, self._loop)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        c = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(qc(self.color, 0.25 + 0.3 * self._pulse if self.busy else 0.22))
        p.drawEllipse(c)
        p.setBrush(qc(self.color))
        p.drawEllipse(c.adjusted(3, 3, -3, -3))


class MainWindow(QMainWindow):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.s = session.settings
        self.setWindowTitle("Трезвонильник")
        self.resize(1280, 800)
        self.setMinimumSize(1020, 660)
        self.popout: StreamWindow | None = None
        self._popover = None
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addWidget(self._build_sidebar())
        layout.addLayout(self._build_center(), 1)
        self.toasts = ToastHost(root)
        self.toasts.enabled = self.s.toasts
        self.overlay = ReactionOverlay(root)
        self.overlay.origin = lambda: self.overlay.mapFromGlobal(self.btn_react.mapToGlobal(QPoint(self.btn_react.width() // 2, 0)))
        self._wire()
        self._shortcuts()
        self.wheel.set_options(self.s.wheel_options)
        self.pad.set_sounds(session.library.sounds)
        self.stage.set_streams([], None, 0)
        self.levels_timer = QTimer(self)
        self.levels_timer.setInterval(50)
        self.levels_timer.timeout.connect(self._tick_levels)
        self.levels_timer.start()
        self.net_timer = QTimer(self)
        self.net_timer.setInterval(1000)
        self.net_timer.timeout.connect(self._tick_net)
        self.net_timer.start()
        self._refresh_controls()

    # ====================================================================== сборка
    def _build_sidebar(self) -> QWidget:
        side = Card(radius=20, fill="bg1")
        side.setFixedWidth(330)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(16, 16, 12, 14)
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.room_icon = AvatarWidget(46, self.s.room_name)
        head.addWidget(self.room_icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.room_title = QLabel("Комната")
        self.room_title.setStyleSheet("font-weight:800;font-size:12pt;")
        col.addWidget(self.room_title)
        st = QHBoxLayout()
        st.setSpacing(7)
        self.dot = StatusDot()
        st.addWidget(self.dot)
        self.status = QLabel("Подключение…")
        self.status.setObjectName("Muted")
        st.addWidget(self.status, 1)
        col.addLayout(st)
        head.addLayout(col, 1)
        self.invite = IconButton("plus", "Скопировать мой IP для приглашения", 34, 0.5, "muted")
        self.invite.clicked.connect(self._copy_ip)
        self.invite.setVisible(self.session.is_host)
        head.addWidget(self.invite)
        lay.addLayout(head)
        row = QHBoxLayout()
        t = QLabel("УЧАСТНИКИ")
        t.setObjectName("Section")
        row.addWidget(t)
        self.count = QLabel("")
        self.count.setObjectName("Faint")
        row.addWidget(self.count)
        row.addStretch(1)
        lay.addLayout(row)
        self.people = ParticipantList()
        lay.addWidget(self.people, 1)
        # собственная панель — как в Discord
        me = Card(radius=16, fill="bg2")
        ml = QHBoxLayout(me)
        ml.setContentsMargins(10, 8, 10, 8)
        ml.setSpacing(10)
        self.me_avatar = AvatarWidget(42, self.session.nickname)
        ml.addWidget(self.me_avatar)
        c2 = QVBoxLayout()
        c2.setSpacing(0)
        nm = QLabel(self.session.nickname)
        nm.setStyleSheet("font-weight:700;")
        c2.addWidget(nm)
        self.me_status = QLabel("")
        self.me_status.setStyleSheet(f"color:{C['muted']};font-size:8.5pt;")
        c2.addWidget(self.me_status)
        ml.addLayout(c2, 1)
        self.btn_mic = RoundButton("mic", "Микрофон  (Ctrl+M)", 40)
        self.btn_deaf = RoundButton("headphones", "Звук  (Ctrl+D)", 40)
        self.btn_settings = RoundButton("gear", "Настройки", 40)
        self.btn_settings.slash_when_off = False
        for b in (self.btn_mic, self.btn_deaf, self.btn_settings):
            ml.addWidget(b)
        lay.addWidget(me)
        return side

    def _build_center(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(14)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.tabs: list[PillButton] = []
        for i, (name, icon) in enumerate((("Трансляции", "screen"), ("Музыка", "music"), ("Колесо", "wheel"))):
            b = PillButton(name, "soft" if i == 0 else "ghost", icon)
            b.clicked.connect(lambda _=False, idx=i: self.show_tab(idx))
            self.tabs.append(b)
            top.addWidget(b)
        self.btn_tts = PillButton("TTS-ка", "ghost", "volume")
        self.btn_tts.setToolTip("Озвучить текст на русском через Google TTS и отправить в комнату")
        self.btn_tts.clicked.connect(self.open_tts)
        top.addWidget(self.btn_tts)
        top.addStretch(1)
        self.net_label = QLabel("")
        self.net_label.setObjectName("Muted")
        top.addWidget(self.net_label)
        col.addLayout(top)
        self.stack = QStackedWidget()
        self.stage = StreamStage()
        self.music = MusicPanel()
        self.wheel = WheelPage()
        for w in (self.stage, self.music, self.wheel):
            self.stack.addWidget(w)
        col.addWidget(self.stack, 1)
        self.pad = SoundPad()
        self.pad.setMaximumHeight(0)
        self.pad.hide()
        col.addWidget(self.pad)
        bar_row = QHBoxLayout()
        bar_row.addStretch(1)
        bar = Card(radius=34, fill="bg1")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.setSpacing(12)
        self.c_mic = RoundButton("mic", "Микрофон  (Ctrl+M)", 54)
        self.c_deaf = RoundButton("headphones", "Выключить звук  (Ctrl+D)", 54)
        self.c_share = RoundButton("screen", "Показать экран", 54)
        self.c_share.slash_when_off = False
        self.btn_react = RoundButton("smile", "Реакции — зажмите эмодзи, чтобы сыпать", 54)
        self.btn_react.slash_when_off = False
        self.c_pad = RoundButton("pad", "Саундпад", 54)
        self.c_pad.slash_when_off = False
        for b in (self.c_mic, self.c_deaf, self.c_share, self.btn_react, self.c_pad):
            bl.addWidget(b)
        bar_row.addWidget(bar)
        bar_row.addStretch(1)
        col.addLayout(bar_row)
        return col

    # ====================================================================== связи
    def _wire(self):
        ss = self.session
        ss.users_updated.connect(self._users)
        ss.avatars_changed.connect(lambda: self._users(ss.users))
        ss.streams_changed.connect(self._streams)
        ss.stream_frame.connect(self._frame)
        ss.my_stream_changed.connect(self._my_stream)
        ss.watchers_changed.connect(lambda n: self._streams())
        ss.connection.connect(self._connection)
        ss.toast.connect(lambda text, kind: self.toasts.show(text, kind))
        ss.kicked_out.connect(self._kicked)
        ss.audio_error.connect(lambda m: self.toasts.show(f"Аудио недоступно: {m}", "error", ms=9000))
        ss.reaction.connect(self._remote_reaction)
        ss.room_named.connect(self._room)
        ss.my_state_changed.connect(self._refresh_controls)
        ss.restrictions_changed.connect(self._restrictions)
        ss.sounds_changed.connect(lambda: self.pad.set_sounds(ss.library.sounds))
        ss.playing_sound.connect(self.pad.set_playing)
        ss.music_state.connect(self.music.set_state)
        ss.music_notice.connect(self._music_notice)
        ss.wheel_remote.connect(self._wheel_remote)
        # управление
        for b in (self.btn_mic, self.c_mic):
            b.clicked.connect(self.toggle_mic)
        for b in (self.btn_deaf, self.c_deaf):
            b.clicked.connect(self.toggle_deaf)
        self.btn_settings.clicked.connect(self.open_settings)
        self.c_share.clicked.connect(self.toggle_share)
        self.btn_react.clicked.connect(self._open_reactions)
        self.c_pad.clicked.connect(self.toggle_pad)
        self.people.watch_clicked.connect(self._watch)
        self.people.context_requested.connect(self._card_menu)
        self.stage.watch_requested.connect(self._watch)
        self.stage.stop_watching.connect(ss.unwatch)
        self.stage.share_requested.connect(self.toggle_share)
        self.stage.popout_requested.connect(self._popout)
        self.pad.play_requested.connect(ss.play_sound)
        self.pad.stop_requested.connect(ss.stop_sound)
        self.pad.add_requested.connect(self._add_sound)
        self.pad.edit_requested.connect(self._edit_sound)
        self.pad.delete_requested.connect(ss.delete_sound)
        self.pad.preview_requested.connect(ss.preview_sound)
        self.pad.pin_requested.connect(lambda sid: ss.edit_sound(sid, pinned=not ss.library.get(sid).pinned))
        self.pad.expand_toggled.connect(lambda on: self._pad_height(EXPANDED_H if on else COLLAPSED_H))
        self.music.command.connect(ss.music_command)
        self.music.volume_changed.connect(self._music_volume)
        self.music.volume.setValue(self.s.music_volume)
        self.wheel.spun.connect(ss.send_wheel)
        self.wheel.options_changed.connect(lambda o: setattr(self.s, "wheel_options", o))

    def _shortcuts(self):
        QShortcut(QKeySequence("Ctrl+M"), self, activated=self.toggle_mic)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self.toggle_deaf)

    def showEvent(self, e):
        super().showEvent(e)
        enable_dark_titlebar(self)

    # ====================================================================== состояние
    def show_tab(self, index: int):
        if self.stack.currentIndex() != index:
            self.stack.setCurrentIndex(index)
            tween.fade_in(self.stack.currentWidget(), 240)
        for i, b in enumerate(self.tabs):
            b.set_kind("soft" if i == index else "ghost")

    def _room(self, name: str):
        self.room_title.setText(name or "Комната")
        self.room_icon.set_nickname(name or "К")
        self.setWindowTitle(f"Трезвонильник — {name}" if name else "Трезвонильник")

    def _connection(self, state: str, text: str):
        self.dot.set_state(state)
        self.status.setText(text if state != "online" else "Подключено")
        self.status.setStyleSheet(f"color:{C[STATE_COLORS.get(state, 'muted')] if state != 'online' else C['muted']};")
        if state == "failed":
            self.toasts.show(text, "error", ms=0)

    def _users(self, users):
        ss = self.session
        avatars = {u["id"]: ss.avatar_for(u["id"]) for u in users}
        self.people.sync(users, ss.my_id, avatars, ss.watching)
        self.count.setText(f"· {len(users)}" if users else "")
        self.me_avatar.set_image(avatars.get(ss.my_id))
        self._refresh_controls()

    def _streams(self):
        ss = self.session
        self.stage.set_streams(ss.streams(), ss.watching, ss.my_id)
        self.people.sync(ss.users, ss.my_id, {u["id"]: ss.avatar_for(u["id"]) for u in ss.users}, ss.watching)
        if ss.watching is None and self.popout:
            self.popout.close()

    def _frame(self, image):
        self.stage.set_frame(image)
        if self.popout:
            self.popout.surface.set_image(image)

    def _refresh_controls(self):
        eng, me = self.session.engine, self.session.me()
        locked = bool(me.get("mic_locked"))
        mic_state = "off" if (eng.muted or locked) else "normal"
        deaf_state = "off" if eng.deafened else "normal"
        for b in (self.btn_mic, self.c_mic):
            b.set_state(mic_state)
            b.setToolTip("Микрофон отключён хостом" if locked else "Микрофон  (Ctrl+M)")
        for b in (self.btn_deaf, self.c_deaf):
            b.set_state(deaf_state)
        if eng.deafened:
            text = "Звук выключен"
        elif locked:
            text = "Микрофон отключён хостом"
        elif eng.muted:
            text = "Микрофон выключен"
        else:
            text = "В эфире"
        self.me_status.setText(text)

    def _restrictions(self):
        self.pad.set_locked(bool(self.session.me().get("sfx_locked")))

    def _my_stream(self, on: bool):
        self.c_share.set_state("on" if on else "normal")
        self.c_share.setToolTip("Остановить демонстрацию" if on else "Показать экран")
        if on:
            self.toasts.show("Демонстрация началась. Кадры отправляются, только пока кто-то смотрит.", "ok")

    # ====================================================================== действия
    def toggle_mic(self):
        self.session.set_muted(not self.session.engine.muted)

    def toggle_deaf(self):
        self.session.set_deafened(not self.session.engine.deafened)

    def toggle_share(self):
        ss = self.session
        if ss.sharing:
            ss.stop_stream()
            return
        if ss.me().get("stream_locked"):
            self.toasts.show("Хост запретил вам трансляции", "warn")
            return
        dlg = SourcePicker(self.s.stream_preset if self.s.stream_preset != "custom" else "balanced", self)
        if dlg.exec() and dlg.selected:
            if ss.start_stream(dlg.selected, dlg.chosen_preset):
                self.show_tab(0)

    def _watch(self, uid: int):
        self.session.watch(uid)
        self.show_tab(0)

    def _popout(self):
        if self.popout:
            self.popout.raise_()
            return
        ss = self.session
        name = (ss.user(ss.watching) or {}).get("nickname", "Трансляция") if ss.watching else "Трансляция"
        self.popout = StreamWindow(f"{name} — Трезвонильник")
        self.popout.closed.connect(lambda: setattr(self, "popout", None))
        self.popout.show()

    def _open_reactions(self):
        bar = ReactionBar(self)
        bar.picked.connect(self._react)
        bar.popup_above(self.btn_react)
        self._react_bar = bar

    def _react(self, emoji: str):
        self.overlay.burst(emoji, local=True)
        self.session.send_reaction(emoji)

    def _remote_reaction(self, uid: int, emoji: str):
        if self.s.reactions:
            u = self.session.user(uid)
            self.overlay.burst(emoji, u["nickname"] if u else "", local=False)

    def toggle_pad(self):
        opening = self.pad.maximumHeight() < 10
        if opening:
            self.pad.show()
            self._pad_height(EXPANDED_H if self.pad.expanded else COLLAPSED_H)
        else:
            tween.tween(self.pad, "maximumHeight", 0, 260, QEasingCurve.InCubic, on_done=self.pad.hide)
        self.c_pad.set_state("on" if opening else "normal")

    def _pad_height(self, h: int):
        self.pad.setMinimumHeight(0)
        tween.tween(self.pad, "maximumHeight", h, 320, QEasingCurve.OutCubic)

    def _add_sound(self):
        dlg = SoundDialog(self)
        if dlg.exec():
            try:
                self.session.add_sound(dlg.path, dlg.name.text(), dlg.emoji.text() or "🔊", dlg.volume.value())
            except Exception as exc:
                self.toasts.show(f"Не удалось добавить звук: {exc}", "error")

    def _edit_sound(self, sid: str):
        s = self.session.library.get(sid)
        if not s:
            return
        dlg = SoundDialog(self, s.name, s.emoji, s.volume, editing=True)
        if dlg.exec():
            self.session.edit_sound(sid, name=dlg.name.text().strip(), emoji=dlg.emoji.text() or "🔊", volume=dlg.volume.value())

    def _music_volume(self, v: int):
        self.s.music_volume = v
        self.session.engine.apply_settings()

    def _music_notice(self, text: str):
        self.music.set_message(text)
        self.toasts.show(("🎵 " if text.startswith("Играет") else "") + text, "info" if text.startswith("Играет") else "warn")

    def _wheel_remote(self, msg: dict, who: str):
        if self.wheel.wheel.spinning:
            return
        self.wheel.play_remote(msg, who)
        if self.stack.currentIndex() != 2:
            self.toasts.show(f"{who} крутит колесо фортуны", "info", ("Смотреть", lambda: self.show_tab(2)), ms=6500)

    def open_tts(self):
        if self.session.me().get("sfx_locked"):
            self.toasts.show("Хост запретил вам использовать звуковые эффекты", "warn")
            return
        self._tts_dialog = TTSDialog(self.s, self)
        self._tts_dialog.play_requested.connect(self._play_tts_pcm)
        self._tts_dialog.exec()

    def _play_tts_pcm(self, pcm):
        if self.session.play_tts(pcm):
            self.toasts.show("Google TTS выходит в эфир", "ok")

    def open_settings(self):
        SettingsDialog(self.session, self).exec()
        self.toasts.enabled = self.s.toasts

    def _copy_ip(self):
        ips = local_ipv4()
        if ips:
            QApplication.clipboard().setText(ips[0])
            self.toasts.show(f"Адрес {ips[0]} скопирован — отправьте друзьям вместе с паролем", "ok")
        else:
            self.toasts.show("Не удалось определить IP", "warn")

    def _kicked(self):
        QMessageBox.warning(self, "Трезвонильник", "Хост исключил вас из комнаты.")
        self.close()

    # ====================================================================== меню участника
    def _card_menu(self, uid: int, pos: QPoint):
        ss = self.session
        u = ss.user(uid)
        if not u:
            return
        me = uid == ss.my_id
        menu = QMenu(self)
        if u.get("sharing") and not me:
            menu.addAction("Смотреть трансляцию").triggered.connect(lambda: self._watch(uid))
        if not me:
            menu.addAction("Громкость и звуки…").triggered.connect(lambda: self._volume_popover(uid, pos))
            menu.addAction("Своя аватарка для этого участника…").triggered.connect(lambda: self._local_avatar(u["nickname"]))
            if u["nickname"] in self.s.local_avatars:
                menu.addAction("Сбросить свою аватарку").triggered.connect(lambda: ss.set_local_avatar(u["nickname"], None))
        if ss.is_host and not u.get("host"):
            menu.addSeparator()
            admin = menu.addMenu("Управление (хост)")
            for text, key in (("Отключить микрофон (глобально)", "mic_locked"), ("Запретить саундпад", "sfx_locked"),
                              ("Запретить трансляции", "stream_locked")):
                act = admin.addAction(text)
                act.setCheckable(True)
                act.setChecked(bool(u.get(key)))
                action = {"mic_locked": "lock_mic", "sfx_locked": "lock_sfx", "stream_locked": "lock_stream"}[key]
                act.triggered.connect(lambda checked, a=action: ss.admin(a, uid, checked))
            stop = admin.addAction("Остановить трансляцию")
            stop.setEnabled(bool(u.get("sharing")))
            stop.triggered.connect(lambda: ss.admin("stop_stream", uid))
            admin.addSeparator()
            admin.addAction("Исключить из комнаты").triggered.connect(lambda: ss.admin("kick", uid))
        if me:
            menu.addAction("Настройки…").triggered.connect(self.open_settings)
        menu.exec(pos)

    def _volume_popover(self, uid: int, pos: QPoint):
        ss = self.session
        u = ss.user(uid)
        st = ss.user_local(uid)
        pop = UserPopover(u["nickname"], st["volume"], st["muted"], st["sfx_muted"], self)
        pop.volume_changed.connect(lambda v: ss.set_user_volume(uid, v))
        pop.muted_changed.connect(lambda v: ss.mute_user(uid, v))
        pop.sfx_muted_changed.connect(lambda v: ss.mute_user_sfx(uid, v))
        pop.popup_at(pos)
        self._popover = pop

    def _local_avatar(self, nickname: str):
        path, _ = QFileDialog.getOpenFileName(self, "Аватарка (её увидите только вы)", "", "Изображения (*.png *.jpg *.jpeg *.gif *.webp)")
        if path:
            try:
                self.session.set_local_avatar(nickname, path)
            except Exception as exc:
                self.toasts.show(f"Не удалось: {exc}", "error")

    # ====================================================================== таймеры
    def _tick_levels(self):
        levels = self.session.levels()
        self.people.set_levels(levels)
        mine = levels.get(self.session.my_id, (False, 0.0))
        self.me_avatar.set_speaking(*mine)

    def _tick_net(self):
        snap = self.session.net_snapshot()
        rtt = f"{snap['rtt_ms']:.0f} мс" if snap["rtt_ms"] is not None else "— мс"
        self.net_label.setText(f"↑ {snap['up_kbps']:.0f}  ↓ {snap['down_kbps']:.0f} кбит/с   ·   {rtt}")
        ss = self.session
        if ss.sharing and ss.streamer:
            self.stage.stats.setText(f"Вы транслируете · зрителей: {ss.watchers} · {ss.streamer.last_frame_bytes // 1024} КБ/кадр")
        elif ss.watching is not None:
            self.stage.stats.setText(f"{ss.receiver.fps:.0f} кадров/с" if ss.watching != ss.my_id else "")
        else:
            self.stage.stats.setText("")

    # ====================================================================== закрытие
    def closeEvent(self, e):
        self.levels_timer.stop()
        self.net_timer.stop()
        self.session._save_settings()
        self.session.close()
        if self.popout:
            self.popout.close()
        super().closeEvent(e)
