from __future__ import annotations
from PySide6.QtCore import QEasingCurve, QObject, QPoint, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ui import tween
from ui.theme import C, qc
from ui.widgets.base import IconButton, PillButton

KIND_COLOR = {"info": "accent2", "ok": "accent", "warn": "warn", "error": "danger"}
W, GAP, MARGIN = 360, 10, 18


class Toast(QWidget):
    def __init__(self, parent, text: str, kind="info", action=None):
        super().__init__(parent)
        self.kind = kind
        row = QHBoxLayout(self)
        row.setContentsMargins(20, 12, 10, 12)
        row.setSpacing(10)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        self.action_btn = None
        if action:
            self.action_btn = PillButton(action[0], "soft", compact=True)
            self.action_btn.clicked.connect(lambda: (action[1](), self.dismiss_requested.emit(self)))
            row.addWidget(self.action_btn)
        close = IconButton("close", "", 24, 0.5)
        close.clicked.connect(lambda: self.dismiss_requested.emit(self))
        row.addWidget(close)
        self.setFixedWidth(W)
        self.adjustSize()
        self.setFixedHeight(max(46, self.sizeHint().height()))

    dismiss_requested = Signal(object)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(qc("border2"), 1))
        p.setBrush(qc("bg2", 0.98))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(qc(KIND_COLOR.get(self.kind, "accent2")))
        p.drawRoundedRect(QRectF(9, 12, 4, r.height() - 24), 2, 2)


class ToastHost(QObject):
    """Стопка уведомлений в правом верхнем углу окна. Въезд с отскоком, плавный пересчёт позиций."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self.window = window
        self.toasts: list[Toast] = []
        self.enabled = True
        window.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.window and event.type() == event.Type.Resize:
            self._layout(animate=False)
        return False

    def show(self, text: str, kind: str = "info", action=None, ms: int = 4200):
        if not self.enabled and kind not in ("error",):
            return
        toast = Toast(self.window, text, kind, action)
        toast.dismiss_requested.connect(self.dismiss)
        while len(self.toasts) >= 5:
            self._remove(self.toasts[0], animate=False)
        y = self._target_y(len(self.toasts), toast)
        toast.move(self.window.width(), y)
        toast.show()
        toast.raise_()
        self.toasts.append(toast)
        tween.tween(toast, "pos", QPoint(self.window.width() - W - MARGIN, y), 420, QEasingCurve.OutBack)
        tween.fade_in(toast, 200)
        if ms > 0:
            QTimer.singleShot(ms, lambda t=toast: self.dismiss(t))
        return toast

    def _target_y(self, index: int, toast: Toast | None = None) -> int:
        y = MARGIN + 6
        for t in self.toasts[:index]:
            y += t.height() + GAP
        return y

    def dismiss(self, toast: Toast):
        if toast in self.toasts:
            self._remove(toast, animate=True)

    def _remove(self, toast: Toast, animate: bool):
        if toast not in self.toasts:
            return
        self.toasts.remove(toast)
        if animate and tween.enabled():
            tween.tween(toast, "pos", QPoint(self.window.width() + 10, toast.y()), 260, QEasingCurve.InCubic,
                        on_done=toast.deleteLater)
        else:
            toast.hide()
            toast.deleteLater()
        self._layout(animate=True)

    def _layout(self, animate=True):
        for i, t in enumerate(self.toasts):
            pos = QPoint(self.window.width() - W - MARGIN, self._target_y(i))
            if animate:
                tween.tween(t, "pos", pos, 280)
            else:
                t.move(pos)
