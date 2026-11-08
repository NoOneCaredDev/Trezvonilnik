from __future__ import annotations
import ipaddress

from PySide6.QtCore import QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QLinearGradient, QPainter
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget)

from app.netinfo import local_ipv4
from ui import theme, tween
from ui.theme import C, mix, qc
from ui.widgets.base import AnimButton, PillButton, _prop


class Brand(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(78)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        f = theme.ui_font(25, 900)
        p.setFont(f)
        g = QLinearGradient(0, 0, 300, 0)
        g.setColorAt(0, qc("accent")); g.setColorAt(1, qc("accent2"))
        p.setPen(Qt.NoPen)
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addText(2, 36, f, "Трезвонильник")
        p.setBrush(g)
        p.drawPath(path)
        p.setPen(qc("muted"))
        p.setFont(theme.ui_font(10))
        p.drawText(QRectF(2, 46, self.width(), 24), Qt.AlignLeft | Qt.AlignVCenter, "голосовая комната для друзей по Radmin VPN")


class Segmented(QWidget):
    changed = Signal(int)
    slide = _prop("slide")

    def __init__(self, options: list[str], parent=None):
        super().__init__(parent)
        self.options = options
        self.index = 0
        self._slide = 0.0
        self.setFixedHeight(44)
        self.setCursor(Qt.PointingHandCursor)

    def set_index(self, i: int, animate=True):
        self.index = i
        if animate:
            tween.tween(self, "slide", float(i), 300, tween.EASE.OutBack)
        else:
            self._slide = float(i)
            self.update()
        self.changed.emit(i)

    def mousePressEvent(self, e):
        i = min(len(self.options) - 1, int(e.position().x() / (self.width() / len(self.options))))
        if i != self.index:
            self.set_index(i)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(qc("border")); p.setBrush(qc("bg1"))
        p.drawRoundedRect(r, 14, 14)
        w = r.width() / len(self.options)
        pill = QRectF(r.left() + 4 + w * self._slide, r.top() + 4, w - 8, r.height() - 8)
        p.setPen(Qt.NoPen); p.setBrush(qc("bg4"))
        p.drawRoundedRect(pill, 10, 10)
        p.setFont(theme.ui_font(10, 700))
        for i, name in enumerate(self.options):
            active = 1.0 - min(1.0, abs(self._slide - i))
            p.setPen(mix(C["muted"], C["text"], active))
            p.drawText(QRectF(r.left() + w * i, r.top(), w, r.height()), Qt.AlignCenter, name)


class Collapsible(QWidget):
    """Поле, которое плавно сворачивается (например, IP хоста не нужен тому, кто сам создаёт комнату)."""
    reveal = _prop("reveal")

    def __init__(self, inner: QWidget, open_=True, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(inner)
        self.inner = inner
        self._reveal = 1.0 if open_ else 0.0
        self._apply()

    def _apply(self):
        h = self.inner.sizeHint().height()
        self.setMaximumHeight(int(h * self._reveal) + (0 if self._reveal > 0.999 else 0))
        self.setVisible(self._reveal > 0.01)

    def update(self, *a):
        self._apply()
        super().update(*a)

    def set_open(self, on: bool, animate=True):
        if animate:
            tween.tween(self, "reveal", 1.0 if on else 0.0, 280, tween.EASE.OutCubic)
        else:
            self._reveal = 1.0 if on else 0.0
            self._apply()


class Field(QWidget):
    def __init__(self, label: str, edit: QLineEdit, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        l = QLabel(label.upper())
        l.setObjectName("Section")
        lay.addWidget(l)
        lay.addWidget(edit)
        self.edit = edit


class LoginDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Трезвонильник")
        self.setFixedWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(34, 28, 34, 30)
        lay.setSpacing(14)
        lay.addWidget(Brand())
        self.mode = Segmented(["Создать комнату", "Подключиться"])
        lay.addWidget(self.mode)
        self.nick = QLineEdit(settings.nickname)
        self.nick.setMaxLength(32)
        lay.addWidget(Field("Никнейм", self.nick))
        self.room = QLineEdit(settings.room_name)
        self.room.setMaxLength(40)
        self.room_field = Collapsible(Field("Название комнаты", self.room))
        lay.addWidget(self.room_field)
        self.ip = QLineEdit(settings.last_host_ip)
        self.ip.setPlaceholderText("например, 26.12.34.56")
        self.ip_field = Collapsible(Field("IP хоста (Radmin VPN)", self.ip), open_=False)
        lay.addWidget(self.ip_field)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("общий пароль комнаты")
        lay.addWidget(Field("Пароль комнаты", self.password))
        # подсказка хосту: какой IP отдавать друзьям
        self.ips = local_ipv4()
        self.my_ip_row = QWidget()
        row = QHBoxLayout(self.my_ip_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.my_ip = QLabel("")
        self.my_ip.setObjectName("Muted")
        self.my_ip.setWordWrap(True)
        row.addWidget(self.my_ip, 1)
        self.copy_btn = PillButton("Копировать", "ghost", compact=True)
        self.copy_btn.clicked.connect(self._copy)
        row.addWidget(self.copy_btn)
        self.ip_hint = Collapsible(self.my_ip_row)
        lay.addWidget(self.ip_hint)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{C['danger']};")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)
        self.go = PillButton("Войти", "primary", "arrow-left")
        self.go.set_icon(None)
        self.go.setMinimumHeight(46)
        self.go.clicked.connect(self._submit)
        lay.addWidget(self.go)
        for e in (self.nick, self.room, self.ip, self.password):
            e.returnPressed.connect(self._submit)
        self.mode.changed.connect(self._mode_changed)
        self.mode.set_index(0 if settings.last_mode != "join" else 1, animate=False)
        self._mode_changed(self.mode.index, animate=False)
        self.password.setFocus()

    def _mode_changed(self, index: int, animate=True):
        host = index == 0
        self.room_field.set_open(host, animate)
        self.ip_field.set_open(not host, animate)
        self.ip_hint.set_open(host and bool(self.ips), animate)
        QTimer.singleShot(340 if animate else 0, self.adjustSize)      # окно сжимается вслед за свёрнутыми полями
        self.go.setText("Создать комнату" if host else "Подключиться")
        self.go.updateGeometry()
        self.error.setText("")
        if self.ips:
            self.my_ip.setText(f"Ваш адрес для друзей: <b style='color:{C['accent']}'>{self.ips[0]}</b>"
                               + (" (Radmin VPN)" if self.ips[0].startswith("26.") else " — Radmin не найден, это обычный адрес"))

    def _copy(self):
        if self.ips:
            QApplication.clipboard().setText(self.ips[0])
            self.copy_btn.setText("Скопировано ✓")

    def _fail(self, widget: QWidget, text: str):
        self.error.setText(text)
        tween.shake(widget)
        widget.setFocus()

    def _submit(self):
        if not self.nick.text().strip():
            return self._fail(self.nick, "Введите никнейм")
        if not self.is_host:
            ip = self.ip.text().strip()
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                return self._fail(self.ip, "Введите IP хоста — адрес вида 26.12.34.56 (его видно в Radmin VPN)")
        if not self.password.text():
            return self._fail(self.password, "Введите пароль комнаты — один и тот же у всех участников")
        s = self.settings
        s.nickname, s.last_mode = self.nick.text().strip(), "host" if self.is_host else "join"
        if self.is_host:
            s.room_name = self.room.text().strip() or "Комната"
        else:
            s.last_host_ip = self.ip.text().strip()
        self.accept()

    @property
    def nickname(self): return self.nick.text().strip() or "Пользователь"
    @property
    def host_ip(self): return self.ip.text().strip()
    @property
    def room_password(self): return self.password.text()
    @property
    def is_host(self): return self.mode.index == 0
    @property
    def room_name(self): return self.room.text().strip() or "Комната"
