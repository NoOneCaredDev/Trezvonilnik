from __future__ import annotations
from PySide6.QtCore import Property, QRectF, Qt, Signal
from PySide6.QtGui import QLinearGradient, QPainter, QPen

from ui import tween
from ui.theme import C, mix, qc
from ui.widgets.base import _prop

DB_MIN, DB_MAX = -80.0, 0.0


class LevelMeter(__import__("PySide6.QtWidgets", fromlist=["QWidget"]).QWidget):
    """Живой индикатор уровня с перетаскиваемым порогом гейта."""
    threshold_changed = Signal(float)
    value = _prop("value")

    def __init__(self, threshold_db: float | None = None, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self.threshold_db = threshold_db
        self.setFixedHeight(26)
        self.setMinimumWidth(180)
        self._dragging = False
        if threshold_db is not None:
            self.setCursor(Qt.SizeHorCursor)
            self.setToolTip("Потяните маркер, чтобы задать порог: ниже него микрофон не передаётся")

    @staticmethod
    def _frac(db: float) -> float:
        return max(0.0, min(1.0, (db - DB_MIN) / (DB_MAX - DB_MIN)))

    def set_level(self, db: float):
        target = self._frac(db)
        # быстрый подъём, медленное падение — как у нормального индикатора
        tween.tween(self, "value", target, 60 if target > self._value else 220)

    def set_threshold(self, db: float):
        self.threshold_db = db
        self.update()

    def _x_to_db(self, x: float) -> float:
        return DB_MIN + max(0.0, min(1.0, x / max(1, self.width()))) * (DB_MAX - DB_MIN)

    def mousePressEvent(self, e):
        if self.threshold_db is not None:
            self._dragging = True
            self._set_from_x(e.position().x())

    def mouseMoveEvent(self, e):
        if self._dragging:
            self._set_from_x(e.position().x())

    def mouseReleaseEvent(self, e):
        self._dragging = False

    def _set_from_x(self, x):
        self.threshold_db = round(self._x_to_db(x))
        self.threshold_changed.emit(float(self.threshold_db))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        bar = QRectF(0, self.height() / 2 - 5, self.width(), 10)
        p.setPen(Qt.NoPen)
        p.setBrush(qc("bg4"))
        p.drawRoundedRect(bar, 5, 5)
        fill = QRectF(bar.left(), bar.top(), bar.width() * self._value, bar.height())
        if fill.width() > 1:
            g = QLinearGradient(bar.topLeft(), bar.topRight())
            g.setColorAt(0.0, qc("ok")); g.setColorAt(0.72, qc("accent")); g.setColorAt(0.88, qc("warn")); g.setColorAt(1.0, qc("danger"))
            p.setBrush(g)
            p.drawRoundedRect(fill, 5, 5)
        if self.threshold_db is not None:
            x = self._frac(self.threshold_db) * self.width()
            open_ = self._frac(self.threshold_db) < self._value
            p.setPen(QPen(mix(C["muted"], C["text"], 1.0 if open_ else 0.0), 2.4, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(int(x), 2, int(x), self.height() - 2)
