from __future__ import annotations
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from ui import tween
from ui.theme import qc
from ui.widgets.base import Switch


class UserPopover(QWidget):
    """Всплывающая панель «громкость и звуки участника» — всё только для вас, сеть об этом не знает."""
    volume_changed = Signal(int)
    muted_changed = Signal(bool)
    sfx_muted_changed = Signal(bool)

    def __init__(self, nickname: str, volume: int, muted: bool, sfx_muted: bool, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedWidth(290)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        t = QLabel(nickname)
        t.setStyleSheet("font-weight:800;font-size:11.5pt;")
        lay.addWidget(t)
        sub = QLabel("Настройки только для вас")
        sub.setObjectName("Muted")
        lay.addWidget(sub)
        row = QHBoxLayout()
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 200)
        self.slider.setValue(volume)
        self.label = QLabel(f"{volume}%")
        self.label.setFixedWidth(46)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.slider.valueChanged.connect(lambda v: (self.label.setText(f"{v}%"), self.volume_changed.emit(v)))
        row.addWidget(self.slider)
        row.addWidget(self.label)
        lay.addLayout(row)
        for text, state, sig in (("Заглушить голос", muted, self.muted_changed), ("Заглушить саундпад", sfx_muted, self.sfx_muted_changed)):
            r = QHBoxLayout()
            r.addWidget(QLabel(text))
            r.addStretch(1)
            sw = Switch(state)
            sw.toggled.connect(sig)
            r.addWidget(sw)
            lay.addLayout(r)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        p.setPen(qc("border2"))
        p.setBrush(qc("bg2", 0.99))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 16, 16)

    def popup_at(self, global_pos: QPoint):
        self.adjustSize()
        self.move(global_pos + QPoint(0, 10))
        self.setWindowOpacity(0.0 if tween.enabled() else 1.0)
        self.show()
        tween.tween(self, "pos", global_pos, 220, tween.EASE.OutCubic)
        tween.tween(self, "windowOpacity", 1.0, 150)
