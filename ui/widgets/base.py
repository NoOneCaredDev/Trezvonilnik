from __future__ import annotations
from PySide6.QtCore import Property, QEasingCurve, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QFrame, QLabel, QSizePolicy, QWidget

from ui import theme, tween
from ui.icons import draw_icon
from ui.theme import C, mix, qc


def _prop(name: str):
    """Float-свойство с авто-перерисовкой: нужно, чтобы tween() мог его анимировать."""
    attr = "_" + name

    def getter(self):
        return getattr(self, attr)

    def setter(self, v):
        setattr(self, attr, float(v))
        self.update()
    return Property(float, getter, setter)


class AnimButton(QAbstractButton):
    """База: hover/press как плавные величины 0..1."""
    hover = _prop("hover")
    press = _prop("press")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = 0.0
        self._press = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)

    def enterEvent(self, e):
        tween.tween(self, "hover", 1.0, 140)
        super().enterEvent(e)

    def leaveEvent(self, e):
        tween.tween(self, "hover", 0.0, 240)
        tween.tween(self, "press", 0.0, 160)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        tween.tween(self, "press", 1.0, 80)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        tween.tween(self, "press", 0.0, 320, QEasingCurve.OutBack)
        super().mouseReleaseEvent(e)

    def changeEvent(self, e):
        self.update()
        super().changeEvent(e)


class RoundButton(AnimButton):
    """Круглая кнопка с иконкой. Состояния: normal / on (акцент) / off (красный + зачёркнуто)."""
    tone_on = _prop("tone_on")
    tone_off = _prop("tone_off")

    def __init__(self, icon: str, tooltip: str = "", size: int = 52, parent=None):
        super().__init__(parent)
        self.icon = icon
        self._tone_on = 0.0
        self._tone_off = 0.0
        self.slash_when_off = True
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)

    def set_state(self, state: str):
        tween.tween(self, "tone_on", 1.0 if state == "on" else 0.0, 260)
        tween.tween(self, "tone_off", 1.0 if state == "off" else 0.0, 260)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        d = self.width()
        scale = 1.0 - 0.08 * self._press + 0.035 * self._hover
        p.translate(d / 2, d / 2)
        p.scale(scale, scale)
        p.translate(-d / 2, -d / 2)
        base = mix(C["bg3"], C["bg4"], self._hover)
        fill = mix(base, mix("#3a1b22", "#4d222b", self._hover), self._tone_off)
        fill = mix(fill, mix(C["accent"], "#9bffe0", self._hover * 0.5), self._tone_on)
        p.setPen(QPen(mix(C["border"], C["border2"], self._hover), 1))
        p.setPen(Qt.NoPen if self._tone_on > 0.5 else p.pen())
        p.setBrush(fill)
        p.drawEllipse(QRectF(0.5, 0.5, d - 1, d - 1))
        icon_color = mix(mix(C["text"], "#ff8a95", self._tone_off), C["bg0"], self._tone_on)
        s = d * 0.42
        slash = qc("danger") if (self.slash_when_off and self._tone_off > 0.5) else None
        draw_icon(p, self.icon, QRectF((d - s) / 2, (d - s) / 2, s, s), icon_color, slash=slash)


class IconButton(AnimButton):
    """Маленькая прозрачная кнопка-иконка."""

    def __init__(self, icon: str, tooltip: str = "", size: int = 32, icon_size: float = 0.55, color: str = "muted", parent=None):
        super().__init__(parent)
        self.icon, self.color_name, self.icon_scale = icon, color, icon_size
        self.hover_color = "text"
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)

    def set_icon(self, name: str):
        self.icon = name
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        d = self.width()
        if self._hover > 0.01:
            p.setPen(Qt.NoPen)
            p.setBrush(qc("bg4", 0.9 * self._hover))
            p.drawRoundedRect(QRectF(0, 0, d, d), d * 0.32, d * 0.32)
        s = d * self.icon_scale * (1 - 0.1 * self._press)
        color = mix(C.get(self.color_name, self.color_name), C[self.hover_color], self._hover)
        if not self.isEnabled():
            color.setAlphaF(0.35)
        draw_icon(p, self.icon, QRectF((d - s) / 2, (d - s) / 2, s, s), color)


class PillButton(AnimButton):
    KINDS = ("primary", "soft", "ghost", "danger")

    def __init__(self, text: str = "", kind: str = "soft", icon: str | None = None, compact: bool = False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.kind, self.icon, self.compact = kind, icon, compact
        self.radius = 11
        self.setFont(theme.ui_font(9.5 if compact else 10, 600))

    def set_kind(self, kind: str):
        self.kind = kind
        self.update()

    def set_icon(self, icon: str | None):
        self.icon = icon
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        fm = QFontMetrics(self.font())
        pad_x, pad_y = (11, 6) if self.compact else (18, 10)
        w = fm.horizontalAdvance(self.text()) + pad_x * 2 + (22 if self.icon and self.text() else (18 if self.icon else 0))
        return QSize(w, fm.height() + pad_y * 2)

    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        sc = 1.0 - 0.03 * self._press
        p.translate(r.center()); p.scale(sc, sc); p.translate(-r.center())
        radius = min(self.radius, r.height() / 2)
        if not self.isEnabled():
            p.setOpacity(0.4)
        text_color = qc("text")
        if self.kind == "primary":
            g = QLinearGradient(r.topLeft(), r.topRight())
            g.setColorAt(0, mix(C["accent"], "#b4ffe9", self._hover * 0.35))
            g.setColorAt(1, mix(C["accent2"], "#a5e6ff", self._hover * 0.35))
            p.setPen(Qt.NoPen); p.setBrush(g)
            text_color = qc("bg0")
        elif self.kind == "danger":
            p.setPen(QPen(mix("#7a3340", C["danger"], self._hover), 1))
            p.setBrush(mix("#2c161c", "#45212a", self._hover))
            text_color = mix("#ff8a95", "#ffb0b8", self._hover)
        elif self.kind == "ghost":
            p.setPen(QPen(mix(C["border2"], C["muted"], self._hover), 1))
            p.setBrush(qc("bg3", 0.9 * self._hover))
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(mix(C["bg3"], C["bg4"], self._hover))
        p.drawRoundedRect(r, radius, radius)
        p.setPen(text_color)
        fm = QFontMetrics(self.font())
        content_w = fm.horizontalAdvance(self.text()) + (22 if self.icon and self.text() else (16 if self.icon else 0))
        x = r.center().x() - content_w / 2
        if self.icon:
            draw_icon(p, self.icon, QRectF(x, r.center().y() - 8, 16, 16), text_color)
            x += 22 if self.text() else 16
        p.setFont(self.font())
        p.drawText(QRectF(x, r.top(), r.right() - x, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())


class Switch(AnimButton):
    knob = _prop("knob")

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._knob = 1.0 if checked else 0.0
        self.setFixedSize(46, 26)
        self.toggled.connect(lambda on: tween.tween(self, "knob", 1.0 if on else 0.0, 260, QEasingCurve.OutBack))

    def setChecked(self, on):          # без анимации при программной установке до показа
        super().setChecked(on)
        if not self.isVisible():
            self._knob = 1.0 if on else 0.0

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        t = max(0.0, min(1.0, self._knob))
        p.setPen(Qt.NoPen)
        p.setBrush(mix(mix(C["bg4"], C["border2"], self._hover), C["accent"], t))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.left() + 3 + (r.width() - d - 6) * self._knob
        p.setBrush(mix(C["text"], C["bg0"], t * 0.9))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class ElidedLabel(QLabel):
    """Подпись, которая обрезается многоточием вместо того, чтобы распирать родителя."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)   # хочет места по тексту, но может сжаться до нуля

    def setText(self, text):
        self._full = text
        super().setText(text)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, e):
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(10, self.width()))
        if shown != self.text():
            QLabel.setText(self, shown)
        super().paintEvent(e)


class IconLabel(QWidget):
    """Крошечная иконка-индикатор (замок, микрофон…)."""

    def __init__(self, icon: str, size: int = 16, color: str = "muted", slash: bool = False, parent=None):
        super().__init__(parent)
        self.icon, self.color, self.slash = icon, color, slash
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        draw_icon(p, self.icon, QRectF(self.rect()).adjusted(1, 1, -1, -1), qc(self.color),
                  width=2.1, slash=qc("danger") if self.slash else None)


class HoverFrame(QFrame):
    hover = _prop("hover")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hover = 0.0

    def enterEvent(self, e):
        tween.tween(self, "hover", 1.0, 160)
        super().enterEvent(e)

    def leaveEvent(self, e):
        tween.tween(self, "hover", 0.0, 260)
        super().leaveEvent(e)


class Card(QFrame):
    """Панель-карточка со скруглением и тонкой рамкой (без QGraphicsEffect: они тормозят перерисовку)."""

    def __init__(self, parent=None, radius=16, fill="bg1"):
        super().__init__(parent)
        self.radius, self.fill = radius, fill

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc("border"), 1))
        p.setBrush(qc(self.fill))
        p.drawRoundedRect(r, self.radius, self.radius)
