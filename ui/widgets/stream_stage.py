from __future__ import annotations
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedLayout, QVBoxLayout, QWidget

from ui import theme, tween
from ui.icons import draw_icon
from ui.theme import C, mix, qc
from ui.widgets.base import Card, IconButton, PillButton, _prop


class VideoSurface(QWidget):
    double_clicked = Signal()

    def __init__(self, parent=None, radius=14):
        super().__init__(parent)
        self.image: QImage | None = None
        self.radius = radius
        self.message = ""
        self.setMinimumSize(320, 200)

    def set_image(self, image: QImage | None):
        self.image = image
        self.update()

    def set_message(self, text: str):
        self.message = text
        self.update()

    def mouseDoubleClickEvent(self, e):
        self.double_clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        r = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(r, self.radius, self.radius)
        p.setClipPath(clip)
        p.fillRect(r, qc("#04080a"))
        if self.image and not self.image.isNull():
            iw, ih = self.image.width(), self.image.height()
            k = min(r.width() / iw, r.height() / ih)
            w, h = iw * k, ih * k
            p.drawImage(QRectF((r.width() - w) / 2, (r.height() - h) / 2, w, h), self.image)
        elif self.message:
            p.setPen(qc("muted"))
            p.setFont(theme.ui_font(10.5))
            p.drawText(r, Qt.AlignCenter, self.message)


class StreamWindow(QWidget):
    """Отдельное окно с трансляцией (двойной клик — полный экран)."""
    closed = Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(title)
        self.setObjectName("Root")
        self.resize(960, 560)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.surface = VideoSurface(radius=10)
        self.surface.double_clicked.connect(self.toggle_fullscreen)
        lay.addWidget(self.surface)

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


class StreamStage(Card):
    """Центральная сцена: чипы активных трансляций + видео, либо пустое состояние."""
    watch_requested = Signal(int)
    stop_watching = Signal()
    popout_requested = Signal()
    share_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, 18, "bg1")
        self.streams: list[dict] = []
        self.watching: int | None = None
        self.self_id = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)
        head = QHBoxLayout()
        title = QLabel("ТРАНСЛЯЦИИ")
        title.setObjectName("Section")
        head.addWidget(title)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        head.addSpacing(8)
        head.addLayout(self.chips)
        head.addStretch(1)
        self.stats = QLabel("")
        self.stats.setObjectName("Muted")
        head.addWidget(self.stats)
        root.addLayout(head)

        host = QWidget()
        self.stack = QStackedLayout(host)
        self.stack.setContentsMargins(0, 0, 0, 0)
        # пустое состояние
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.addStretch(1)
        self.empty_icon = _EmptyIcon()
        ev.addWidget(self.empty_icon, 0, Qt.AlignHCenter)
        self.empty_title = QLabel("Пока никто не транслирует")
        self.empty_title.setObjectName("H2")
        self.empty_title.setAlignment(Qt.AlignCenter)
        ev.addWidget(self.empty_title)
        self.empty_text = QLabel("Покажите экран или окно — друзья смогут смотреть, не отрываясь от звонка.")
        self.empty_text.setObjectName("Muted")
        self.empty_text.setAlignment(Qt.AlignCenter)
        self.empty_text.setWordWrap(True)
        ev.addWidget(self.empty_text)
        ev.addSpacing(10)
        btn = PillButton("Начать демонстрацию", "primary", "screen")
        btn.clicked.connect(self.share_requested)
        ev.addWidget(btn, 0, Qt.AlignHCenter)
        ev.addStretch(2)
        self.stack.addWidget(empty)
        # видео
        video_host = QWidget()
        vl = QVBoxLayout(video_host)
        vl.setContentsMargins(0, 0, 0, 0)
        self.surface = VideoSurface()
        vl.addWidget(self.surface)
        self.stack.addWidget(video_host)
        self.overlay_label = QLabel(self.surface)
        self.overlay_label.setStyleSheet(f"background:{C['bg0']}cc;border-radius:10px;padding:5px 11px;font-weight:700;")
        self.overlay_label.move(12, 12)
        self.overlay_label.hide()
        self.btn_pop = IconButton("expand", "Открыть в окне", 34, 0.55, "text", self.surface)
        self.btn_stop = IconButton("close", "Перестать смотреть", 34, 0.5, "text", self.surface)
        for b in (self.btn_pop, self.btn_stop):
            b.setStyleSheet("")
        self.btn_pop.clicked.connect(self.popout_requested)
        self.btn_stop.clicked.connect(self.stop_watching)
        root.addWidget(host, 1)
        self.surface.installEventFilter(self)
        self._place_buttons()
        self._refresh()

    def eventFilter(self, obj, ev):
        if obj is self.surface and ev.type() == ev.Type.Resize:
            self._place_buttons()
        return False

    def _place_buttons(self):
        w = self.surface.width()
        self.btn_stop.move(w - 12 - 34, 12)
        self.btn_pop.move(w - 12 - 34 * 2 - 6, 12)

    def set_streams(self, streams: list[dict], watching: int | None, self_id: int):
        self.streams, self.watching, self.self_id = streams, watching, self_id
        self._refresh()

    def set_frame(self, image: QImage):
        if self.watching is not None:
            self.surface.set_image(image)

    def _refresh(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for s in self.streams:
            mine = s["id"] == self.self_id
            chip = PillButton(("Ваш экран" if mine else s["nickname"]), "primary" if s["id"] == self.watching else "soft",
                              "screen", compact=True)
            chip.clicked.connect(lambda _=False, uid=s["id"]: self.watch_requested.emit(uid))
            self.chips.addWidget(chip)
        if self.watching is None:
            self.stack.setCurrentIndex(0)
            self.surface.set_image(None)
            self.empty_title.setText("Сейчас никто не транслирует" if not self.streams else "Выберите трансляцию")
            self.empty_text.setText("Покажите экран или окно — друзья смогут смотреть, не отрываясь от звонка."
                                    if not self.streams else "Нажмите на имя вверху или на «Смотреть» у участника.")
            self.overlay_label.hide()
        else:
            if self.stack.currentIndex() != 1:
                self.stack.setCurrentIndex(1)
                self.surface.set_image(None)
                tween.fade_in(self.surface, 280)
            s = next((x for x in self.streams if x["id"] == self.watching), None)
            name = "Ваш экран" if self.watching == self.self_id else (s["nickname"] if s else "Трансляция")
            title = f" · {s['stream_title']}" if s and s.get("stream_title") else ""
            self.overlay_label.setText(f"<span style='color:{C['live']}'>●</span> {name}{title}")
            self.overlay_label.adjustSize()
            self.overlay_label.show()
            if self.surface.image is None:
                self.surface.set_message("Подключаемся к трансляции…")
            self.btn_stop.raise_(); self.btn_pop.raise_()


class _EmptyIcon(QWidget):
    pulse = _prop("pulse")

    def __init__(self):
        super().__init__()
        self._pulse = 0.0
        self.setFixedSize(96, 96)

    def showEvent(self, e):
        self._loop()
        super().showEvent(e)

    def _loop(self):
        if not self.isVisible():
            return
        up = self._pulse < 0.5
        tween.tween(self, "pulse", 1.0 if up else 0.0, 1800, tween.EASE.InOutSine, on_done=self._loop)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        c = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(qc("accent", 0.05 + 0.05 * self._pulse))
        k = 6 * self._pulse
        p.drawEllipse(c.adjusted(-k, -k, k, k).adjusted(0, 0, 0, 0))
        p.setBrush(qc("bg3"))
        p.drawEllipse(c.adjusted(8, 8, -8, -8))
        draw_icon(p, "screen", c.adjusted(28, 28, -28, -28), mix(C["muted"], C["accent"], self._pulse), 1.7)
