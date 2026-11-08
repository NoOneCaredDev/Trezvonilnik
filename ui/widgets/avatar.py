from __future__ import annotations
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QMovie, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

from ui import theme, tween
from ui.icons import draw_icon
from ui.theme import C, avatar_color, mix, qc
from ui.widgets.base import _prop


class AvatarWidget(QWidget):
    """Круглая аватарка: заглушка с буквой / картинка / анимированный WebP;
    кольцо «говорит» плавно появляется и пульсирует по громкости."""
    ring = _prop("ring")
    pop = _prop("pop")

    def __init__(self, size: int = 44, nickname: str = "?", parent=None):
        super().__init__(parent)
        self.nickname = nickname
        self._ring = 0.0
        self._pop = 0.0
        self.level = 0.0
        self.badge: str | None = None
        self.pixmap: QPixmap | None = None
        self.movie: QMovie | None = None
        self._buffer: QBuffer | None = None
        self._data: bytes | None = None
        self.ring_color = "accent"
        self.setFixedSize(size, size)
        self._speaking = False

    # --- содержимое ----------------------------------------------------------
    def set_nickname(self, nick: str):
        if nick != self.nickname:
            self.nickname = nick
            self.update()

    def set_image(self, data: bytes | None):
        if data == self._data:
            return
        self._data = data
        self._drop_movie()
        self.pixmap = None
        if data:
            buf = QBuffer(self)
            buf.setData(QByteArray(data))
            buf.open(QIODevice.ReadOnly)
            movie = QMovie(buf, QByteArray(), self)
            movie.jumpToFrame(0)
            if movie.isValid() and movie.frameCount() > 1:
                self.movie, self._buffer = movie, buf
                movie.frameChanged.connect(lambda _=0: self.update())
                if self.isVisible():
                    movie.start()
            else:
                self.pixmap = movie.currentPixmap() if movie.isValid() else QPixmap.fromImage(QImage.fromData(data))
                movie.deleteLater()
                buf.deleteLater()
                if self.pixmap.isNull():
                    self.pixmap = None
        if self.pixmap or self.movie:
            tween.tween(self, "pop", 1.0, 420, tween.EASE.OutBack, start=0.0)
        self.update()

    def _drop_movie(self):
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None
        if self._buffer:
            self._buffer.deleteLater()
            self._buffer = None

    def showEvent(self, e):
        if self.movie:
            self.movie.start()
        super().showEvent(e)

    def hideEvent(self, e):
        if self.movie:
            self.movie.setPaused(True)
        super().hideEvent(e)

    # --- состояние -----------------------------------------------------------
    def set_speaking(self, speaking: bool, level: float = 0.0):
        self.level = level
        if speaking != self._speaking:
            self._speaking = speaking
            tween.tween(self, "ring", 1.0 if speaking else 0.0, 140 if speaking else 320)
        elif speaking:
            self.update()

    def set_badge(self, icon: str | None):
        if icon != self.badge:
            self.badge = icon
            self.update()

    # --- рисование -----------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        d = self.width()
        pad = max(3.0, d * 0.07)
        inner = QRectF(pad, pad, d - 2 * pad, d - 2 * pad)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.save()
        p.setClipPath(clip)
        frame = None
        if self.movie:
            frame = self.movie.currentPixmap()
        elif self.pixmap:
            frame = self.pixmap
        if frame is not None and not frame.isNull():
            k = 0.82 + 0.18 * self._pop
            c = inner.center()
            target = QRectF(0, 0, inner.width() * k, inner.height() * k)
            target.moveCenter(c)
            p.drawPixmap(target.toRect(), frame)
        else:
            base = avatar_color(self.nickname)
            g = QRadialGradient(inner.center() - QPointF(inner.width() * .2, inner.height() * .25), inner.width())
            g.setColorAt(0, base.lighter(125)); g.setColorAt(1, base.darker(135))
            p.fillRect(inner, g)
            p.setPen(QColor("#0b1013"))
            f = theme.ui_font(d * 0.27, 800)
            p.setFont(f)
            p.drawText(inner, Qt.AlignCenter, (self.nickname or "?")[:1].upper())
        p.restore()
        # кольцо «говорит»
        if self._ring > 0.01:
            col = qc(self.ring_color)
            pulse = 0.5 + 0.5 * min(1.0, self.level * 1.6)
            col.setAlphaF(self._ring)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(col, 1.6 + 1.6 * pulse * self._ring))
            ring_rect = inner.adjusted(-pad * 0.55, -pad * 0.55, pad * 0.55, pad * 0.55)
            p.drawEllipse(ring_rect)
            glow = qc(self.ring_color, 0.20 * self._ring * pulse)
            p.setPen(QPen(glow, 3.2))
            p.drawEllipse(ring_rect.adjusted(-2.2, -2.2, 2.2, 2.2))
        if self.badge:
            r = d * 0.36
            br = QRectF(d - r, d - r, r, r)
            p.setPen(QPen(qc("bg2"), 2))
            p.setBrush(qc("#3a1b22"))
            p.drawEllipse(br)
            draw_icon(p, self.badge, br.adjusted(r * .2, r * .2, -r * .2, -r * .2), qc("#ff8a95"), width=2.3,
                      slash=qc("danger") if self.badge in ("mic", "headphones") else None)
