from __future__ import annotations
from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout

from config.settings import STREAM_PRESETS
from media.video.capture import CaptureSource, list_sources, thumbnail
from ui.theme import C
from ui.widgets.base import PillButton
from ui.widgets.stream_stage import VideoSurface


def bgr_to_qimage(frame) -> QImage:
    h, w = frame.shape[:2]
    return QImage(frame.data, w, h, frame.strides[0], QImage.Format_BGR888).copy()


class SourcePicker(QDialog):
    """Выбор, что показывать: экран или окно. Справа живой предпросмотр — до того, как вас кто-то увидит."""

    def __init__(self, preset: str, parent=None, sources: list[CaptureSource] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Что показываем?")
        self.resize(920, 560)
        self.selected: CaptureSource | None = None
        self.sources = sources if sources is not None else list_sources()
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)
        t = QLabel("Что показываем?")
        t.setObjectName("H1")
        root.addWidget(t)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.list = QListWidget()
        self.list.setFixedWidth(300)
        self.list.setIconSize(QSize(120, 68))
        self.list.setSpacing(3)
        body.addWidget(self.list)
        right = QVBoxLayout()
        self.preview = VideoSurface()
        self.preview.set_message("Выберите источник слева")
        right.addWidget(self.preview, 1)
        hint = QLabel("Предпросмотр — только для вас: зрители увидят то же самое после нажатия «Начать». "
                      "Отдельные вкладки браузера показать нельзя — выберите окно браузера целиком.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        right.addWidget(hint)
        body.addLayout(right, 1)
        root.addLayout(body, 1)
        row = QHBoxLayout()
        self.preset = QComboBox()
        for key, p in STREAM_PRESETS.items():
            self.preset.addItem(p["title"], key)
        i = self.preset.findData(preset)
        self.preset.setCurrentIndex(max(0, i))
        row.addWidget(QLabel("Качество:"))
        row.addWidget(self.preset)
        row.addStretch(1)
        cancel = PillButton("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        self.go = PillButton("Начать трансляцию", "primary", "play")
        self.go.setEnabled(False)
        self.go.clicked.connect(self._accept)
        row.addWidget(cancel)
        row.addWidget(self.go)
        root.addLayout(row)
        for src in self.sources:
            item = QListWidgetItem(("🖥  " if src.kind == "monitor" else "🗔  ") + src.title)
            item.setData(Qt.UserRole, src)
            item.setSizeHint(QSize(280, 78))
            self.list.addItem(item)
            thumb = thumbnail(src, 240)
            if thumb is not None:
                item.setIcon(QIcon(QPixmap.fromImage(bgr_to_qimage(thumb))))
        if not self.sources:
            self.preview.set_message("Не найдено ни одного экрана или окна для захвата")
        self.list.currentItemChanged.connect(self._changed)
        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._refresh)
        self.timer.start()
        if self.sources:
            self.list.setCurrentRow(0)

    def _changed(self, item):
        self.selected = item.data(Qt.UserRole) if item else None
        self.go.setEnabled(self.selected is not None)
        self._refresh()

    def _refresh(self):
        if self.selected is None:
            return
        frame = thumbnail(self.selected, 800)
        if frame is not None:
            self.preview.set_image(bgr_to_qimage(frame))
        else:
            self.preview.set_message("Окно свёрнуто или недоступно")

    def _accept(self):
        self.timer.stop()
        self.accept()

    def reject(self):
        self.timer.stop()
        super().reject()

    @property
    def chosen_preset(self) -> str:
        return self.preset.currentData()
