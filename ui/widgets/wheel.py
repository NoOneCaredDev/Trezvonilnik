from __future__ import annotations
import math
import random

from PySide6.QtCore import Property, QEasingCurve, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget)

from ui import theme, tween
from ui.theme import C, mix, qc
from ui.widgets.base import Card, IconButton, PillButton, Switch, _prop

SPIN_MS = 5200


def sector_color(i: int) -> QColor:
    return QColor.fromHsv((i * 43 + 160) % 360, 120, 205)


def pick_winner(weights: list[float], rng=random) -> tuple[int, float]:
    """Честный выбор с учётом весов + случайная точка внутри сектора (не в самом краю)."""
    winner = rng.choices(range(len(weights)), weights=weights, k=1)[0]
    return winner, rng.uniform(0.12, 0.88)


def final_angle(weights: list[float], winner: int, offset: float, turns: float) -> float:
    """Угол (по часовой), на котором под указателем окажется точка offset сектора winner.
    Обороты — только целые: дробная часть сдвинула бы остановку на чужой сектор."""
    total = sum(weights)
    start = sum(weights[:winner]) / total * 360.0
    pos = start + offset * weights[winner] / total * 360.0
    return 360.0 * max(1, math.floor(turns)) - pos


def sector_at_pointer(weights: list[float], angle: float) -> int:
    total = sum(weights)
    pos = (-angle) % 360.0
    acc = 0.0
    for i, w in enumerate(weights):
        acc += w / total * 360.0
        if pos < acc:
            return i
    return len(weights) - 1


class WheelWidget(QWidget):
    finished = Signal(int)
    tick = _prop("tick")
    win = _prop("win")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.options: list[str] = ["Да", "Нет"]
        self.weights: list[float] = [1.0, 1.0]
        self._angle_ = 0.0
        self._tick = 0.0
        self._win = 0.0
        self.winner: int | None = None
        self._last_sector = 0
        self.spinning = False
        self.setMinimumSize(320, 320)

    # angle — свойство со своим сеттером: заодно ловим момент пересечения границы сектора
    def _get_angle(self):
        return self._angle_

    def _set_angle(self, v):
        self._angle_ = float(v)
        if self.spinning and len(self.weights) > 1:
            s = sector_at_pointer(self.weights, self._angle_)
            if s != self._last_sector:
                self._last_sector = s
                self._tick = 1.0
                tween.tween(self, "tick", 0.0, 140, QEasingCurve.OutCubic)
        self.update()
    angle = Property(float, _get_angle, _set_angle)

    def set_data(self, options: list[str], weights: list[float]):
        self.options, self.weights = list(options), [max(0.01, float(w)) for w in weights]
        self.winner = None
        self._win = 0.0
        self.update()

    def spin_to(self, winner: int, offset: float, turns: float, ms: int = SPIN_MS):
        if self.spinning or len(self.options) < 2:
            return
        self.spinning, self.winner, self._win = True, None, 0.0
        start = self._angle_ % 360.0
        self._angle_ = start
        end = final_angle(self.weights, winner, offset, turns)
        while end < start + 720:
            end += 360.0

        def done():
            self.spinning = False
            self.winner = winner
            tween.tween(self, "win", 1.0, 520, QEasingCurve.OutBack)
            self.finished.emit(winner)
        tween.tween(self, "angle", end, ms, QEasingCurve.OutQuart, start=start, on_done=done)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        side = (min(self.width(), self.height()) - 8) / 1.2 - 14
        c = QPointF(self.width() / 2, self.height() / 2 + 8)
        R = side / 2
        rect = QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R)
        total = sum(self.weights)
        # свечение и обод
        glow = QRadialGradient(c, R * 1.18)
        glow.setColorAt(0.82, qc("accent", 0.0)); glow.setColorAt(0.9, qc("accent", 0.10)); glow.setColorAt(1.0, qc("accent", 0.0))
        p.setPen(Qt.NoPen); p.setBrush(glow)
        p.drawEllipse(c, R * 1.18, R * 1.18)
        p.setBrush(qc("bg3"))
        p.drawEllipse(c, R + 7, R + 7)
        acc = 0.0
        label_font = theme.ui_font(max(8.0, min(12.5, R / 16)), 700)
        for i, (name, w) in enumerate(zip(self.options, self.weights)):
            span = w / total * 360.0
            start = acc + self._angle_
            pop = self._win * 7 if self.winner == i else 0.0
            sec_rect = rect.adjusted(-pop, -pop, pop, pop)
            col = sector_color(i)
            if self.winner is not None and self.winner != i:
                col = mix(col, QColor(C["bg1"]), 0.62 * self._win)
            p.setPen(QPen(qc("bg1"), 2))
            p.setBrush(col)
            p.drawPie(sec_rect, int((90 - start) * 16), int(-span * 16))
            # подпись вдоль радиуса
            mid = math.radians(start + span / 2 - 90)
            p.save()
            p.translate(c)
            p.rotate(math.degrees(mid))
            p.setFont(label_font)
            fm = QFontMetricsF(label_font)
            avail = R * 0.74
            text = fm.elidedText(name, Qt.ElideRight, avail)
            if span > 6:
                p.setPen(QColor("#0b1115"))
                p.drawText(QRectF(R * 0.22, -fm.height() / 2, avail, fm.height()), Qt.AlignVCenter | Qt.AlignRight, text)
            p.restore()
            acc += span
        # втулка
        hub = QRadialGradient(c, R * 0.2)
        hub.setColorAt(0, qc("bg4")); hub.setColorAt(1, qc("bg2"))
        p.setPen(QPen(qc("border2"), 2)); p.setBrush(hub)
        p.drawEllipse(c, R * 0.15, R * 0.15)
        # указатель (сверху) — дёргается при каждом щелчке сектора
        p.save()
        p.translate(c.x(), c.y() - R - 4)
        p.rotate(-14 * self._tick)
        path = QPainterPath()
        path.moveTo(0, 16); path.lineTo(-13, -16); path.lineTo(13, -16); path.closeSubpath()
        p.setPen(QPen(qc("bg0"), 2)); p.setBrush(mix(C["text"], C["danger"], 0.5 + 0.5 * self._tick))
        p.drawPath(path)
        p.restore()


class OptionRow(QWidget):
    changed = Signal()
    removed = Signal(object)

    def __init__(self, name="", weight=1.0, color=None, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.dot = QLabel()
        self.dot.setFixedSize(12, 12)
        row.addWidget(self.dot)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("Вариант")
        self.name.setMaxLength(40)
        self.name.textChanged.connect(lambda: self.changed.emit())
        row.addWidget(self.name, 1)
        self.weight = QDoubleSpinBox()
        self.weight.setRange(0.1, 100)
        self.weight.setSingleStep(0.5)
        self.weight.setDecimals(1)
        self.weight.setFixedWidth(70)
        self.weight.setValue(weight)
        self.weight.setToolTip("Вес варианта: чем больше, тем больше шанс")
        self.weight.valueChanged.connect(lambda: self.changed.emit())
        row.addWidget(self.weight)
        self.percent = QLabel("")
        self.percent.setObjectName("Muted")
        self.percent.setFixedWidth(46)
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.percent)
        rm = IconButton("close", "Убрать вариант", 30, 0.5)
        rm.clicked.connect(lambda: self.removed.emit(self))
        row.addWidget(rm)

    def set_look(self, index: int, percent: float):
        self.dot.setStyleSheet(f"background:{sector_color(index).name()};border-radius:6px;")
        self.percent.setText(f"{percent:.0f}%" if percent >= 1 else f"{percent:.1f}%")


class WheelPage(Card):
    spun = Signal(dict)              # параметры вращения — чтобы показать колесо остальным
    options_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent, 18, "bg1")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(20)
        # ---- редактор
        left = QVBoxLayout()
        title = QLabel("КОЛЕСО ФОРТУНЫ")
        title.setObjectName("Section")
        left.addWidget(title)
        hint = QLabel("Впишите варианты и задайте им вес — шансы пересчитаются сами.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        left.addWidget(hint)
        self.rows_host = QWidget()
        self.rows_host.setAttribute(Qt.WA_TranslucentBackground)
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 4, 0)
        self.rows.setSpacing(7)
        self.rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rows_host)
        scroll.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
        left.addWidget(scroll, 1)
        add_row = QHBoxLayout()
        self.add_btn = PillButton("Вариант", "soft", "plus", compact=True)
        self.add_btn.clicked.connect(lambda: self.add_row("", 1.0, focus=True))
        add_row.addWidget(self.add_btn)
        self.reset_btn = PillButton("Сбросить", "ghost", compact=True)
        self.reset_btn.clicked.connect(self.reset)
        add_row.addWidget(self.reset_btn)
        add_row.addStretch(1)
        left.addLayout(add_row)
        outer.addLayout(left, 5)
        # ---- колесо
        right = QVBoxLayout()
        self.wheel = WheelWidget()
        self.wheel.finished.connect(self._finished)
        right.addWidget(self.wheel, 1)
        self.result = QLabel("")
        self.result.setAlignment(Qt.AlignCenter)
        self.result.setStyleSheet("font-size:17pt;font-weight:800;")
        self.result.setMinimumHeight(34)
        right.addWidget(self.result)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.share = Switch(True)
        self.share.setToolTip("Остальные в комнате увидят это же вращение")
        bottom.addWidget(self.share)
        lab = QLabel("Показать всем")
        lab.setObjectName("Muted")
        bottom.addWidget(lab)
        bottom.addSpacing(16)
        self.spin_btn = PillButton("Крутить!", "primary", "dice")
        self.spin_btn.clicked.connect(self.spin)
        bottom.addWidget(self.spin_btn)
        bottom.addStretch(1)
        right.addLayout(bottom)
        outer.addLayout(right, 6)
        self._rows: list[OptionRow] = []
        self._locked_by: str | None = None
        self.set_options(None)

    # --- данные ---------------------------------------------------------------
    def set_options(self, options: list[dict] | None):
        for r in list(self._rows):
            self._drop(r, notify=False)
        for o in options or [{"name": "Да", "weight": 1}, {"name": "Нет", "weight": 1}]:
            self.add_row(o.get("name", ""), float(o.get("weight", 1.0)), notify=False)
        self._sync()

    def add_row(self, name="", weight=1.0, focus=False, notify=True):
        if len(self._rows) >= 24:
            return
        row = OptionRow(name, weight)
        row.changed.connect(self._sync)
        row.removed.connect(self._drop)
        self.rows.insertWidget(self.rows.count() - 1, row)
        self._rows.append(row)
        if tween.enabled():
            tween.fade_in(row, 220)
        if focus:
            row.name.setFocus()
        if notify:
            self._sync()

    def _drop(self, row, notify=True):
        if row in self._rows:
            self._rows.remove(row)
            self.rows.removeWidget(row)
            row.deleteLater()
            if notify:
                self._sync()

    def reset(self):
        self.set_options([{"name": "Да", "weight": 1}, {"name": "Нет", "weight": 1}])
        self.options_changed.emit(self.current())

    def current(self) -> list[dict]:
        return [{"name": r.name.text().strip(), "weight": r.weight.value()} for r in self._rows]

    def _valid(self):
        items = [(o["name"], o["weight"]) for o in self.current() if o["name"]]
        return items

    def _sync(self):
        items = self._valid()
        total = sum(w for _, w in items) or 1.0
        idx = 0
        for r in self._rows:
            if r.name.text().strip():
                r.set_look(idx, r.weight.value() / total * 100)
                idx += 1
            else:
                r.dot.setStyleSheet(f"background:{C['bg4']};border-radius:6px;")
                r.percent.setText("")
        if len(items) >= 2:
            self.wheel.set_data([n for n, _ in items], [w for _, w in items])
        else:
            self.wheel.set_data(["Добавьте", "варианты"], [1, 1])
        self.spin_btn.setEnabled(len(items) >= 2 and not self.wheel.spinning and not self._locked_by)
        self.options_changed.emit(self.current())

    # --- вращение -------------------------------------------------------------
    def spin(self):
        items = self._valid()
        if len(items) < 2 or self.wheel.spinning:
            return
        weights = [w for _, w in items]
        winner, offset = pick_winner(weights)
        turns = random.uniform(5.0, 8.0)
        self._begin(items and [n for n, _ in items], weights, winner, offset, turns)
        if self.share.isChecked():
            self.spun.emit({"options": [n for n, _ in items], "weights": weights, "winner": winner,
                            "offset": offset, "turns": turns})

    def play_remote(self, msg: dict, who: str):
        """Чужое вращение: показываем те же варианты и тот же результат."""
        if self.wheel.spinning:
            return
        self._locked_by = who
        self.wheel.set_data(msg["options"], msg["weights"])
        self.result.setText(f"{who} крутит колесо…")
        self.result.setStyleSheet(f"font-size:12pt;font-weight:700;color:{C['muted']};")
        self.spin_btn.setEnabled(False)
        self.wheel.spin_to(msg["winner"], msg.get("offset", 0.5), msg["turns"])

    def _begin(self, names, weights, winner, offset, turns):
        self._locked_by = None
        self.wheel.set_data(names, weights)
        self.result.setText("")
        self.spin_btn.setEnabled(False)
        self.wheel.spin_to(winner, offset, turns)

    def _finished(self, winner: int):
        name = self.wheel.options[winner]
        self.result.setText(f"🎯 {name}")
        self.result.setStyleSheet(f"font-size:17pt;font-weight:800;color:{C['accent']};")
        self._locked_by = None
        self._sync_after_spin()

    def _sync_after_spin(self):
        self.spin_btn.setEnabled(len(self._valid()) >= 2)
