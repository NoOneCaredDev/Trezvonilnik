from __future__ import annotations
from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, Signal, QPoint
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from ui import tween
from ui.theme import C, mix, qc
from ui.widgets.avatar import AvatarWidget
from ui.widgets.base import ElidedLabel, HoverFrame, IconLabel, PillButton, _prop

CARD_H = 64


class UserCard(HoverFrame):
    watch_clicked = Signal(int)
    context_requested = Signal(int, QPoint)
    glow = _prop("glow")
    sel = _prop("sel")

    def __init__(self, uid: int, parent=None):
        super().__init__(parent)
        self.uid = uid
        self._glow = 0.0
        self._sel = 0.0
        self.setMinimumHeight(CARD_H)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self.context_requested.emit(self.uid, self.mapToGlobal(pos)))
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 8, 12, 8)
        row.setSpacing(12)
        self.avatar = AvatarWidget(44)
        row.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = ElidedLabel()
        self.name.setStyleSheet("font-weight:700;")
        top.addWidget(self.name)
        self.host_icon = IconLabel("crown", 14, "host")
        self.host_icon.setToolTip("Хост комнаты")
        top.addWidget(self.host_icon)
        self.you_tag = QLabel("ВЫ")
        self.you_tag.setStyleSheet(f"color:{C['accent']};font-size:7.5pt;font-weight:800;letter-spacing:1px;")
        top.addWidget(self.you_tag)
        top.addStretch(1)
        col.addLayout(top)
        self.subtitle = ElidedLabel()
        self.subtitle.setObjectName("Muted")
        self.subtitle.setStyleSheet(f"color:{C['muted']};font-size:9pt;")
        col.addWidget(self.subtitle)
        row.addLayout(col, 1)
        self.lock_icon = IconLabel("lock", 15, "warn")
        row.addWidget(self.lock_icon)
        self.deaf_icon = IconLabel("headphones", 16, "muted", slash=True)
        row.addWidget(self.deaf_icon)
        self.mic_icon = IconLabel("mic", 16, "muted", slash=True)
        row.addWidget(self.mic_icon)
        self.watch_btn = PillButton("Смотреть", "primary", "eye", compact=True)
        self.watch_btn.clicked.connect(lambda: self.watch_clicked.emit(self.uid))
        row.addWidget(self.watch_btn)
        self._speaking = False
        self._user: dict = {}

    def update_user(self, user: dict, is_self: bool, avatar: bytes | None, watching: bool):
        self._user = user
        nick = user.get("nickname", "?")
        self.name.setText(nick)
        self.avatar.set_nickname(nick)
        self.avatar.set_image(avatar)
        self.host_icon.setVisible(bool(user.get("host")))
        self.you_tag.setVisible(is_self)
        muted, deaf = bool(user.get("muted")), bool(user.get("deafened"))
        locked = bool(user.get("mic_locked"))
        self.mic_icon.setVisible(muted or locked)
        self.deaf_icon.setVisible(deaf)
        self.lock_icon.setVisible(bool(user.get("sfx_locked") or user.get("stream_locked") or locked))
        locks = [n for n, k in (("микрофон", "mic_locked"), ("саундпад", "sfx_locked"), ("трансляции", "stream_locked")) if user.get(k)]
        self.lock_icon.setToolTip("Хост запретил: " + ", ".join(locks) if locks else "")
        sharing = bool(user.get("sharing"))
        self.watch_btn.setVisible(sharing and not is_self)
        self.watch_btn.setText("Смотрю" if watching else "Смотреть")
        self.watch_btn.set_kind("soft" if watching else "primary")
        self._sharing, self._muted, self._deaf, self._title = sharing, muted, deaf, user.get("stream_title", "")
        self._is_self = is_self
        tween.tween(self, "sel", 1.0 if watching else 0.0, 220)
        self._refresh_subtitle()

    def set_speaking(self, speaking: bool, level: float):
        self.avatar.set_speaking(speaking, level)
        if speaking != self._speaking:
            self._speaking = speaking
            tween.tween(self, "glow", 1.0 if speaking else 0.0, 160 if speaking else 360)
            self._refresh_subtitle()

    def _refresh_subtitle(self):
        if getattr(self, "_sharing", False):
            text = "Транслирует" + (f" · {self._title}" if self._title else "")
            color = C["live"]
        elif self._speaking:
            text, color = "Говорит", C["accent"]
        elif getattr(self, "_deaf", False):
            text, color = "Не слышит", C["muted"]
        elif getattr(self, "_muted", False):
            text, color = "Микрофон выключен", C["muted"]
        else:
            text, color = "На связи", C["muted"]
        self.subtitle.setText(text)
        self.subtitle.setStyleSheet(f"color:{color};font-size:9pt;")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        fill = mix(mix(C["bg2"], C["bg3"], self._hover), mix(C["bg3"], "#18352f", 1), self._glow * 0.55)
        border = mix(mix(C["border"], C["border2"], self._hover), C["accent"], self._glow * 0.85)
        border = mix(border, C["accent2"], self._sel)
        p.setPen(QPen(border, 1.0 + 0.8 * max(self._glow, self._sel)))
        p.setBrush(fill)
        p.drawRoundedRect(r, 14, 14)


class ParticipantList(QScrollArea):
    watch_clicked = Signal(int)
    context_requested = Signal(int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setAttribute(Qt.WA_TranslucentBackground)
        self.setWidget(inner)
        self.layout_ = QVBoxLayout(inner)
        self.layout_.setContentsMargins(0, 0, 4, 0)
        self.layout_.setSpacing(7)
        self.layout_.addStretch(1)
        self.cards: dict[int, UserCard] = {}
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet('QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}')

    def sync(self, users: list[dict], self_id: int, avatars: dict[int, bytes | None], watching: int | None):
        ids = [u["id"] for u in users]
        for uid in [i for i in self.cards if i not in ids]:
            self._remove(uid)
        for user in users:
            uid = user["id"]
            card = self.cards.get(uid)
            fresh = card is None
            if fresh:
                card = UserCard(uid)
                card.watch_clicked.connect(self.watch_clicked)
                card.context_requested.connect(self.context_requested)
                self.cards[uid] = card
                self.layout_.insertWidget(self.layout_.count() - 1, card)
            card.update_user(user, uid == self_id, avatars.get(uid), watching == uid)
            if fresh:
                self._appear(card)
        self._reorder(ids)

    def _reorder(self, ids: list[int]):
        """Порядок как в списке сервера (хост первым). Уходящие карточки остаются на месте до конца анимации."""
        live = {id(c) for c in self.cards.values()}
        current = []
        for i in range(self.layout_.count() - 1):
            w = self.layout_.itemAt(i).widget()
            if w is not None and id(w) in live:
                current.append(w.uid)
        if current == ids:
            return
        for i, uid in enumerate(ids):
            card = self.cards[uid]
            self.layout_.removeWidget(card)
            self.layout_.insertWidget(i, card)

    def _appear(self, card: UserCard):
        if tween.enabled():
            card.setMinimumHeight(0)
            card.setMaximumHeight(0)

            def done():
                card.setMinimumHeight(CARD_H)
                card.setMaximumHeight(16777215)
            tween.tween(card, "maximumHeight", CARD_H, 320, QEasingCurve.OutCubic, on_done=done)
            tween.fade_in(card, 320)

    def _remove(self, uid: int):
        card = self.cards.pop(uid, None)
        if not card:
            return

        def gone():
            self.layout_.removeWidget(card)
            card.deleteLater()
        if tween.enabled():
            card.setMinimumHeight(0)
            card.setMaximumHeight(max(card.height(), 1))
            tween.fade_out(card, 200)
            tween.tween(card, "maximumHeight", 0, 260, QEasingCurve.InCubic, on_done=gone)
        else:
            gone()

    def set_levels(self, levels: dict[int, tuple[bool, float]]):
        for uid, card in self.cards.items():
            speaking, level = levels.get(uid, (False, 0.0))
            card.set_speaking(speaking, level)
