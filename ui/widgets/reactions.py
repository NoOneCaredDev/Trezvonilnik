from __future__ import annotations
import math
import random
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QWidget

from ui import theme, tween
from ui.theme import C, qc
from ui.widgets.base import AnimButton, _prop

EMOJIS = ["😂", "❤️", "🔥", "💩", "👏", "😮", "😭", "🎉", "👍", "💀"]
MAX_PARTICLES = 140


def _emoji_pixmap(cache: dict, emoji: str, px: int = 72) -> QPixmap:
    pm = cache.get(emoji)
    if pm is None:
        pm = QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.setFont(theme.emoji_font(px * 0.52 * 0.75))
        p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, emoji)
        p.end()
        cache[emoji] = pm
    return pm


class _Particle:
    __slots__ = ("emoji", "x", "y", "vx", "vy", "born", "life", "sway", "phase", "size", "name")


class ReactionOverlay(QWidget):
    """Прозрачный слой поверх окна. Эмодзи — частицы: рисуем из кэша пиксмапов, поэтому
    даже «срачь в звонке» из сотни 💩 не нагружает интерфейс."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.particles: list[_Particle] = []
        self.cache: dict[str, QPixmap] = {}
        self.origin = lambda: QPoint(self.width() // 2, self.height() - 80)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._last = time.monotonic()
        parent.installEventFilter(self)
        self.setGeometry(parent.rect())
        self.raise_()
        self.show()

    def eventFilter(self, obj, event):
        if obj is self.parent() and event.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
            self.raise_()
        return False

    def burst(self, emoji: str, name: str = "", local: bool = False, count: int = 1):
        for _ in range(count):
            part = _Particle()
            o = self.origin()
            part.emoji, part.name = emoji, name
            if local:
                part.x, part.y = o.x() + random.uniform(-26, 26), o.y() - 20
            else:
                part.x = random.uniform(self.width() * 0.3, self.width() * 0.92)
                part.y = self.height() - random.uniform(30, 90)
            part.vx = random.uniform(-26, 26)
            part.vy = -random.uniform(150, 290)
            part.born, part.life = time.monotonic(), random.uniform(2.3, 3.5)
            part.sway, part.phase = random.uniform(14, 40), random.uniform(0, 6.28)
            part.size = random.uniform(40, 58)
            self.particles.append(part)
        del self.particles[:-MAX_PARTICLES]
        if not self.timer.isActive():
            self._last = time.monotonic()
            self.timer.start()

    def _tick(self):
        now = time.monotonic()
        dt, self._last = min(0.05, now - self._last), now
        for p in self.particles:
            p.x += p.vx * dt
            p.y += p.vy * dt
            p.vy *= 0.992
        self.particles = [p for p in self.particles if now - p.born < p.life and p.y > -80]
        if not self.particles:
            self.timer.stop()
        self.update()

    def paintEvent(self, e):
        if not self.particles:
            return
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        now = time.monotonic()
        name_font = theme.ui_font(8.5, 700)
        for part in self.particles:
            age = now - part.born
            t = age / part.life
            pop = min(1.0, age / 0.28)
            scale = 0.3 + 0.7 * (1 + 2.2 * (pop - 1) ** 3 + 1.2 * (pop - 1) ** 2) if pop < 1 else 1.0   # «отскок» при появлении
            alpha = 1.0 if t < 0.72 else max(0.0, (1 - t) / 0.28)
            x = part.x + math.sin(age * 2.4 + part.phase) * part.sway
            p.save()
            p.setOpacity(alpha)
            p.translate(x, part.y)
            p.rotate(math.sin(age * 2.0 + part.phase) * 9)
            s = part.size * scale
            p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), _emoji_pixmap(self.cache, part.emoji), QRectF(self.cache[part.emoji].rect()))
            if part.name and age < part.life * 0.8:
                p.setFont(name_font)
                fm = QFontMetricsF(name_font)
                w = fm.horizontalAdvance(part.name) + 14
                p.setPen(Qt.NoPen)
                p.setBrush(qc("bg0", 0.78))
                p.drawRoundedRect(QRectF(-w / 2, s / 2 + 1, w, 17), 8.5, 8.5)
                p.setPen(qc("text"))
                p.drawText(QRectF(-w / 2, s / 2 + 1, w, 17), Qt.AlignCenter, part.name)
            p.restore()


class EmojiButton(AnimButton):
    """Эмодзи в панели реакций. Пока кнопку держат — реакции сыплются (режим «срать в звонке»)."""
    fired = Signal(str)

    def __init__(self, emoji: str, parent=None):
        super().__init__(parent)
        self.emoji = emoji
        self.setFixedSize(46, 46)
        self.setToolTip("Нажмите или зажмите — чтобы сыпать")
        self.repeat = QTimer(self)
        self.repeat.setInterval(95)
        self.repeat.timeout.connect(lambda: self.fired.emit(self.emoji))

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.fired.emit(self.emoji)
        self.repeat.start()

    def mouseReleaseEvent(self, e):
        self.repeat.stop()
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        self.repeat.stop()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        d = self.width()
        if self._hover > 0.01:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("bg4", self._hover))
            p.drawRoundedRect(QRectF(2, 2, d - 4, d - 4), 14, 14)
        k = 1.0 + 0.28 * self._hover - 0.18 * self._press
        p.translate(d / 2, d / 2); p.scale(k, k); p.translate(-d / 2, -d / 2)
        p.setFont(theme.emoji_font(17))
        p.drawText(QRectF(0, 0, d, d), Qt.AlignCenter, self.emoji)


class ReactionBar(QWidget):
    picked = Signal(str)
    shown = _prop("shown")

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._shown = 0.0
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(2)
        for emoji in EMOJIS:
            b = EmojiButton(emoji)
            b.fired.connect(self.picked)
            row.addWidget(b)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        p.setPen(qc("border2"))
        p.setBrush(qc("bg2", 0.99))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 22, 22)

    def popup_above(self, anchor: QWidget):
        self.adjustSize()
        g = anchor.mapToGlobal(QPoint(anchor.width() // 2, 0))
        target = QPoint(g.x() - self.width() // 2, g.y() - self.height() - 14)
        self.move(target + QPoint(0, 14))
        self.setWindowOpacity(0.0 if tween.enabled() else 1.0)
        self.show()
        tween.tween(self, "pos", target, 260, tween.EASE.OutBack)
        tween.tween(self, "windowOpacity", 1.0, 160)
