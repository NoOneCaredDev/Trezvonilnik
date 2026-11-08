from __future__ import annotations
import math
import time

from PySide6.QtCore import QPoint, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea,
                               QSlider, QVBoxLayout, QWidget)

from ui import theme, tween
from ui.icons import draw_icon
from ui.theme import C, mix, qc
from ui.widgets.base import AnimButton, Card, IconButton, PillButton, _prop

TILE_W, TILE_H, GAP = 96, 78, 9
COLLAPSED_H, EXPANDED_H = 150, 340


class SoundTile(AnimButton):
    playing = _prop("playing")
    context_requested = Signal(str, QPoint)

    def __init__(self, sound_id: str | None, emoji: str, name: str, pinned=False, locked=False, parent=None):
        super().__init__(parent)
        self.sound_id, self.emoji, self.name, self.pinned, self.locked = sound_id, emoji, name, pinned, locked
        self._playing = 0.0
        self.setFixedSize(TILE_W, TILE_H)
        self.setToolTip(name if sound_id else "Добавить звук")
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: sound_id and self.context_requested.emit(sound_id, self.mapToGlobal(pos)))

    def set_playing(self, on: bool):
        tween.tween(self, "playing", 1.0 if on else 0.0, 200)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        k = 1.0 - 0.05 * self._press + 0.015 * self._hover
        p.translate(r.center()); p.scale(k, k); p.translate(-r.center())
        if not self.isEnabled() or self.locked:
            p.setOpacity(0.45)
        if self.sound_id is None:                                    # плитка «＋»
            p.setPen(QPen(mix(C["border2"], C["accent"], self._hover), 1.4, Qt.DashLine))
            p.setBrush(qc("accent", 0.06 * self._hover))
            p.drawRoundedRect(r, 14, 14)
            draw_icon(p, "plus", QRectF(r.center().x() - 11, r.center().y() - 11, 22, 22), mix(C["muted"], C["accent"], self._hover), 2.1)
            return
        fill = mix(mix(C["bg2"], C["bg3"], self._hover), "#17433a", self._playing * 0.8)
        p.setPen(QPen(mix(mix(C["border"], C["border2"], self._hover), C["accent"], self._playing), 1 + self._playing))
        p.setBrush(fill)
        p.drawRoundedRect(r, 14, 14)
        p.setFont(theme.emoji_font(19))
        bounce = -3 * math.sin(time.monotonic() * 14) * self._playing
        p.setPen(qc("text"))
        p.drawText(QRectF(r.left(), r.top() + 6 + bounce, r.width(), 36), Qt.AlignCenter, self.emoji)
        f = theme.ui_font(8.8, 600)
        p.setFont(f)
        p.setPen(qc("text") if self._hover > 0.2 else qc("muted"))
        text = QFontMetricsF(f).elidedText(self.name, Qt.ElideRight, r.width() - 12)
        p.drawText(QRectF(r.left() + 6, r.bottom() - 28, r.width() - 12, 22), Qt.AlignCenter, text)
        if self.pinned:
            p.setPen(Qt.NoPen); p.setBrush(qc("accent", 0.9))
            p.drawEllipse(QRectF(r.right() - 13, r.top() + 7, 6, 6))


class SoundPad(Card):
    play_requested = Signal(str)
    stop_requested = Signal()
    add_requested = Signal()
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    pin_requested = Signal(str)
    preview_requested = Signal(str)
    expand_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent, 18, "bg1")
        self.sounds = []
        self.tiles: dict[str, SoundTile] = {}
        self.expanded = False
        self.locked = False
        self._cols = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 12, 12)
        root.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("САУНДПАД")
        t.setObjectName("Section")
        head.addWidget(t)
        self.note = QLabel("")
        self.note.setObjectName("Muted")
        head.addWidget(self.note)
        head.addStretch(1)
        self.stop_btn = IconButton("stop", "Остановить звук", 30, 0.5)
        self.stop_btn.clicked.connect(self.stop_requested)
        head.addWidget(self.stop_btn)
        self.expand_btn = IconButton("expand", "Показать все звуки", 30, 0.5)
        self.expand_btn.clicked.connect(self.toggle_expanded)
        head.addWidget(self.expand_btn)
        root.addLayout(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GAP)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(self.grid_host)
        root.addWidget(self.scroll, 1)

    def toggle_expanded(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, on: bool):
        self.expanded = on
        self.expand_btn.setToolTip("Свернуть" if on else "Показать все звуки")
        self._relayout(force=True)
        self.expand_toggled.emit(on)

    def set_locked(self, locked: bool):
        self.locked = locked
        self.note.setText("· хост запретил вам саундпад" if locked else "")
        self.note.setStyleSheet(f"color:{C['warn']};")
        for t in self.tiles.values():
            t.locked = locked
            t.update()

    def set_sounds(self, sounds):
        self.sounds = list(sounds)
        self._relayout(force=True)

    def set_playing(self, sound_id: str | None):
        for sid, tile in self.tiles.items():
            tile.set_playing(sid == sound_id)
        self._playing = sound_id
        if sound_id and not hasattr(self, "_anim_timer"):
            self._anim_timer = QTimer(self)
            self._anim_timer.setInterval(33)
            self._anim_timer.timeout.connect(lambda: [t.update() for t in self.tiles.values() if t._playing > 0.01])
        if hasattr(self, "_anim_timer"):
            self._anim_timer.start() if sound_id else self._anim_timer.stop()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()

    def _relayout(self, force=False):
        width = self.scroll.viewport().width() or max(300, self.width() - 40)
        cols = max(1, (width + GAP) // (TILE_W + GAP))
        if cols == self._cols and not force:
            return
        self._cols = cols
        for i in reversed(range(self.grid.count())):
            w = self.grid.itemAt(i).widget()
            self.grid.removeWidget(w)
            if not isinstance(w, SoundTile) or w.sound_id is None or w.sound_id not in {s.id for s in self.sounds}:
                w.deleteLater()
        visible = self.sounds if self.expanded else [s for s in self.sounds if s.pinned]
        if not self.expanded and not visible:
            visible = self.sounds[:6]
        old = self.tiles
        self.tiles = {}
        for s in visible:
            tile = old.pop(s.id, None) or self._make_tile(s)
            tile.emoji, tile.name, tile.pinned, tile.locked = s.emoji, s.name, s.pinned, self.locked
            tile.setToolTip(s.name)
            self.tiles[s.id] = tile
        for w in old.values():
            w.deleteLater()
        items = list(self.tiles.values())
        add = SoundTile(None, "", "")
        add.clicked.connect(self.add_requested)
        items.append(add)
        for i, w in enumerate(items):
            self.grid.addWidget(w, i // cols, i % cols)
            w.show()
        if hasattr(self, "_playing"):
            self.set_playing(self._playing)

    def _make_tile(self, s):
        tile = SoundTile(s.id, s.emoji, s.name, s.pinned)
        tile.clicked.connect(lambda _=False, sid=s.id: (None if self.locked else self.play_requested.emit(sid)))
        tile.context_requested.connect(self._menu)
        return tile

    def _menu(self, sound_id: str, pos: QPoint):
        sound = next((s for s in self.sounds if s.id == sound_id), None)
        if not sound:
            return
        menu = QMenu(self)
        menu.addAction("Прослушать (только вам)").triggered.connect(lambda: self.preview_requested.emit(sound_id))
        menu.addAction("Изменить…").triggered.connect(lambda: self.edit_requested.emit(sound_id))
        menu.addAction("Открепить от панели" if sound.pinned else "Закрепить на панели").triggered.connect(lambda: self.pin_requested.emit(sound_id))
        menu.addSeparator()
        menu.addAction("Удалить").triggered.connect(lambda: self.delete_requested.emit(sound_id))
        menu.exec(pos)


QUICK_EMOJI = ["🎺", "😂", "🔥", "💩", "👀", "🎉", "🤡", "💀", "🥁", "🔔", "👏", "😱"]


class SoundDialog(QDialog):
    """Добавление/редактирование звука."""

    def __init__(self, parent=None, name="", emoji="🔊", volume=100, path="", editing=False, on_preview=None):
        super().__init__(parent)
        self.setWindowTitle("Изменить звук" if editing else "Новый звук")
        self.setMinimumWidth(420)
        self.path = path
        self.on_preview = on_preview
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(10)
        h = QLabel("Изменить звук" if editing else "Добавить звук")
        h.setObjectName("H2")
        lay.addWidget(h)
        if not editing:
            row = QHBoxLayout()
            self.file_label = QLabel("Файл не выбран")
            self.file_label.setObjectName("Muted")
            row.addWidget(self.file_label, 1)
            pick = PillButton("Выбрать файл…", "soft", "upload", compact=True)
            pick.clicked.connect(self._pick)
            row.addWidget(pick)
            lay.addLayout(row)
            hint = QLabel("WAV, MP3, OGG, FLAC… — до 20 секунд. Файл копируется в папку приложения.")
            hint.setObjectName("Faint")
            hint.setWordWrap(True)
            lay.addWidget(hint)
        lay.addWidget(self._lbl("Название"))
        self.name = QLineEdit(name)
        self.name.setMaxLength(24)
        lay.addWidget(self.name)
        lay.addWidget(self._lbl("Эмодзи"))
        er = QHBoxLayout()
        self.emoji = QLineEdit(emoji)
        self.emoji.setMaxLength(4)
        self.emoji.setFixedWidth(70)
        er.addWidget(self.emoji)
        for em in QUICK_EMOJI:
            b = PillButton(em, "ghost", compact=True)
            b.setFont(theme.emoji_font(11))
            b.clicked.connect(lambda _=False, v=em: self.emoji.setText(v))
            er.addWidget(b)
        er.addStretch(1)
        lay.addLayout(er)
        lay.addWidget(self._lbl("Громкость"))
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(10, 200)
        self.volume.setValue(volume)
        lay.addWidget(self.volume)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{C['danger']};")
        lay.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PillButton("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        ok = PillButton("Сохранить" if editing else "Добавить", "primary")
        ok.clicked.connect(self._accept)
        buttons.addWidget(cancel)
        buttons.addWidget(ok)
        lay.addLayout(buttons)
        self.editing = editing

    @staticmethod
    def _lbl(text):
        l = QLabel(text.upper())
        l.setObjectName("Section")
        return l

    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать звук", "", "Аудио (*.wav *.mp3 *.ogg *.flac *.m4a *.opus);;Все файлы (*)")
        if path:
            self.path = path
            import os
            self.file_label.setText(os.path.basename(path))
            if not self.name.text():
                self.name.setText(os.path.splitext(os.path.basename(path))[0][:24])

    def _accept(self):
        if not self.editing and not self.path:
            self.error.setText("Выберите файл")
            tween.shake(self.error)
            return
        if not self.name.text().strip():
            self.error.setText("Введите название")
            return
        self.accept()
