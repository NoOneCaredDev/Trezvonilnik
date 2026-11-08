from __future__ import annotations
import math
import time

from PySide6.QtCore import QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSlider, QVBoxLayout, QWidget

from ui import theme, tween
from ui.icons import draw_icon
from ui.theme import C, mix, qc
from ui.widgets.base import Card, IconButton, PillButton, RoundButton, _prop


def fmt_time(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


class EqBars(QWidget):
    """Крошечный «эквалайзер» — просто чтобы было видно, что играет."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 18)
        self.active = False
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.update)

    def set_active(self, on: bool):
        self.active = on
        self.timer.start() if on else self.timer.stop()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("accent") if self.active else qc("faint"))
        t = time.monotonic()
        for i in range(4):
            h = 5 + (0.5 + 0.5 * math.sin(t * (5 + i * 1.7) + i)) * 11 if self.active else 4
            p.drawRoundedRect(QRectF(1 + i * 5.5, self.height() - h, 3.5, h), 1.5, 1.5)


class ProgressBar(QWidget):
    seek_ratio = Signal(float)
    value = _prop("value")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(14)

    def set_value(self, frac: float, smooth_ms=0):
        frac = max(0.0, min(1.0, frac))
        if smooth_ms:
            tween.tween(self, "value", frac, smooth_ms, tween.EASE.Linear)
        else:
            self._value = frac
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        bar = QRectF(0, self.height() / 2 - 3, self.width(), 6)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("bg4"))
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(qc("accent"))
        p.drawRoundedRect(QRectF(0, bar.top(), max(6.0, bar.width() * self._value), 6), 3, 3)
        if self._value > 0:
            p.setBrush(qc("text"))
            p.drawEllipse(QRectF(bar.width() * self._value - 6, self.height() / 2 - 6, 12, 12))


class MusicPanel(Card):
    command = Signal(dict)
    volume_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent, 18, "bg1")
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 18)
        root.setSpacing(12)
        head = QHBoxLayout()
        t = QLabel("МУЗЫКАЛЬНЫЙ БОТ")
        t.setObjectName("Section")
        head.addWidget(t)
        head.addStretch(1)
        sub = QLabel("играет с компьютера хоста")
        sub.setObjectName("Faint")
        head.addWidget(sub)
        root.addLayout(head)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Ссылка на YouTube, SoundCloud или Spotify — или просто название трека")
        self.input.returnPressed.connect(self._add)
        row.addWidget(self.input, 1)
        self.add_btn = PillButton("Добавить", "primary", "plus")
        self.add_btn.clicked.connect(self._add)
        row.addWidget(self.add_btn)
        root.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setVisible(False)
        root.addWidget(self.status)

        now = Card(radius=16, fill="bg2")
        nl = QVBoxLayout(now)
        nl.setContentsMargins(18, 14, 18, 14)
        nl.setSpacing(8)
        top = QHBoxLayout()
        self.eq = EqBars()
        top.addWidget(self.eq)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.title = QLabel("Ничего не играет")
        self.title.setStyleSheet("font-size:12.5pt;font-weight:800;")
        self.title.setWordWrap(False)
        titles.addWidget(self.title)
        self.artist = QLabel("Добавьте трек — он сразу начнёт играть у всех")
        self.artist.setObjectName("Muted")
        titles.addWidget(self.artist)
        top.addLayout(titles, 1)
        nl.addLayout(top)
        self.progress = ProgressBar()
        nl.addWidget(self.progress)
        times = QHBoxLayout()
        self.t_pos = QLabel("0:00")
        self.t_pos.setObjectName("Muted")
        self.t_len = QLabel("")
        self.t_len.setObjectName("Muted")
        times.addWidget(self.t_pos)
        times.addStretch(1)
        times.addWidget(self.t_len)
        nl.addLayout(times)
        ctl = QHBoxLayout()
        ctl.setSpacing(10)
        self.pause_btn = RoundButton("pause", "Пауза / продолжить", 46)
        self.pause_btn.clicked.connect(lambda: self.command.emit({"action": "pause"}))
        self.skip_btn = RoundButton("skip", "Следующий", 40)
        self.skip_btn.clicked.connect(lambda: self.command.emit({"action": "skip"}))
        self.stop_btn = RoundButton("stop", "Остановить и очистить очередь", 40)
        self.stop_btn.clicked.connect(lambda: self.command.emit({"action": "stop"}))
        for b in (self.pause_btn, self.skip_btn, self.stop_btn):
            ctl.addWidget(b)
        ctl.addStretch(1)
        vol_icon = IconButton("volume", "", 28, 0.6)
        vol_icon.setEnabled(False)
        ctl.addWidget(vol_icon)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 150)
        self.volume.setFixedWidth(130)
        self.volume.setToolTip("Громкость музыки — только у вас")
        self.volume.valueChanged.connect(self.volume_changed)
        ctl.addWidget(self.volume)
        nl.addLayout(ctl)
        root.addWidget(now)

        qh = QHBoxLayout()
        ql = QLabel("ОЧЕРЕДЬ")
        ql.setObjectName("Section")
        qh.addWidget(ql)
        self.queue_count = QLabel("")
        self.queue_count.setObjectName("Faint")
        qh.addWidget(self.queue_count)
        qh.addStretch(1)
        root.addLayout(qh)
        self.queue_host = QWidget()
        self.queue_host.setAttribute(Qt.WA_TranslucentBackground)
        self.queue_layout = QVBoxLayout(self.queue_host)
        self.queue_layout.setContentsMargins(0, 0, 4, 0)
        self.queue_layout.setSpacing(6)
        self.queue_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.queue_host)
        scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        root.addWidget(scroll, 1)

        self._state: dict = {}
        self._base_pos = 0.0
        self._t0 = time.monotonic()
        self._dots = 0
        self.ticker = QTimer(self)
        self.ticker.setInterval(250)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start()
        self.set_state({"now": None, "queue": [], "paused": False, "pos": 0, "resolving": 0})

    def _add(self):
        text = self.input.text().strip()
        if text:
            self.command.emit({"action": "add", "url": text})
            self.input.clear()

    def set_message(self, text: str):
        self.status.setText(text)
        self.status.setVisible(bool(text))
        if text:
            QTimer.singleShot(6000, lambda: self.status.text() == text and self.status.setVisible(False))

    def set_state(self, st: dict):
        self._state = st
        now = st.get("now")
        paused = bool(st.get("paused"))
        self.eq.set_active(bool(now) and not paused)
        if now:
            self.title.setText(now["title"])
            by = f" · добавил(а) {now['by']}" if now.get("by") else ""
            self.artist.setText((now.get("artist") or "—") + by)
            self.t_len.setText(fmt_time(now["duration"]) if now.get("duration") else "")
        else:
            self.title.setText("Ничего не играет")
            self.artist.setText("Добавьте трек — он сразу начнёт играть у всех")
            self.t_len.setText("")
        self.pause_btn.icon = "play" if paused else "pause"
        self.pause_btn.update()
        for b in (self.pause_btn, self.skip_btn, self.stop_btn):
            b.setEnabled(bool(now))
        self._base_pos, self._t0 = float(st.get("pos", 0)), time.monotonic()
        self._rebuild_queue(st.get("queue", []))
        resolving = st.get("resolving", 0)
        if resolving:
            self.status.setVisible(True)
        elif self.status.text().startswith("Ищем"):
            self.status.setVisible(False)
        self._tick()

    def _tick(self):
        st = self._state
        now = st.get("now")
        if st.get("resolving"):
            self._dots = (self._dots + 1) % 4
            self.status.setText("Ищем трек" + "." * self._dots)
            self.status.setVisible(True)
        if not now:
            self.t_pos.setText("0:00")
            self.progress.set_value(0)
            return
        pos = self._base_pos + (0 if st.get("paused") else time.monotonic() - self._t0)
        if now.get("duration"):
            pos = min(pos, now["duration"])
            self.progress.set_value(pos / now["duration"], 260)
        else:
            self.progress.set_value(0)
        self.t_pos.setText(fmt_time(pos))

    def _rebuild_queue(self, queue: list):
        while self.queue_layout.count() > 1:
            item = self.queue_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.queue_count.setText(f"· {len(queue)}" if queue else "")
        if not queue:
            empty = QLabel("Очередь пуста")
            empty.setObjectName("Faint")
            self.queue_layout.insertWidget(0, empty)
        for i, track in enumerate(queue):
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(12, 6, 6, 6)
            rl.setSpacing(10)
            n = QLabel(str(i + 1))
            n.setObjectName("Faint")
            n.setFixedWidth(18)
            rl.addWidget(n)
            tl = QLabel(f"{track['title']}" + (f"  <span style='color:{C['muted']}'>— {track['artist']}</span>" if track.get("artist") else ""))
            rl.addWidget(tl, 1)
            dur = QLabel(fmt_time(track["duration"]) if track.get("duration") else "")
            dur.setObjectName("Muted")
            rl.addWidget(dur)
            rm = IconButton("close", "Убрать из очереди", 28, 0.5)
            rm.clicked.connect(lambda _=False, idx=i: self.command.emit({"action": "remove", "index": idx}))
            rl.addWidget(rm)
            row.setStyleSheet(f"background:{C['bg2']};border-radius:11px;")
            self.queue_layout.insertWidget(i, row)
            tween.fade_in(row, 200)
