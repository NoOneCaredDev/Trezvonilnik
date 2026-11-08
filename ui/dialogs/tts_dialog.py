from __future__ import annotations

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTextEdit, QVBoxLayout)

from media.tts.google import MAX_TEXT, synthesize
from ui.theme import C


class _TTSWorker(QThread):
    done = Signal(object, dict)
    failed = Signal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text

    def run(self):
        try:
            pcm, info = synthesize(self.text)
            self.done.emit(pcm, info)
        except Exception as exc:
            self.failed.emit(str(exc))


class TTSDialog(QDialog):
    play_requested = Signal(object)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.worker = None
        self.setWindowTitle("TTS-ка · Google · русский")
        self.setMinimumSize(560, 390)
        self.resize(620, 440)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(12)

        title = QLabel("Озвучка текста через Google")
        title.setStyleSheet("font-size:16pt;font-weight:800;")
        root.addWidget(title)
        subtitle = QLabel(
            "Русская речь через gTTS. Готовая озвучка отправится всем участникам голосовой комнаты. "
            "API-ключ и регистрация не нужны."
        )
        subtitle.setObjectName("Muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        root.addWidget(self._label("Текст для озвучки"))
        self.text = QTextEdit()
        self.text.setPlaceholderText("Привет, кожаные человеки…")
        self.text.setAcceptRichText(False)
        self.text.setMinimumHeight(150)
        self.text.textChanged.connect(self._count)
        root.addWidget(self.text, 1)
        self.counter = QLabel(f"0 / {MAX_TEXT}")
        self.counter.setObjectName("Muted")
        self.counter.setAlignment(Qt.AlignRight)
        root.addWidget(self.counter)

        note = QLabel(
            "Нужен доступ к интернету: gTTS получает аудио через сервис Google Translate. "
            "Это бесплатный неофициальный интерфейс Google Translate TTS, а не Google Cloud Text-to-Speech."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        root.addWidget(note)

        self.status = QLabel("Готово к озвучке")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.send = QPushButton("Озвучить и отправить")
        self.send.setDefault(True)
        self.send.clicked.connect(self._start)
        self.close_button = QPushButton("Закрыть")
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        buttons.addWidget(self.send)
        root.addLayout(buttons)
        self.setStyleSheet(f"""
            QLineEdit, QTextEdit {{ background:{C['bg2']}; border:1px solid {C['border']};
                border-radius:9px; padding:8px; selection-background-color:{C['accent']}; }}
            QPushButton {{ background:{C['bg3']}; border:1px solid {C['border']}; border-radius:9px;
                padding:9px 14px; font-weight:600; }}
            QPushButton:hover {{ background:{C['bg4']}; }}
            QPushButton:disabled {{ color:{C['muted']}; }}
        """)

    @staticmethod
    def _label(text):
        label = QLabel(text)
        label.setStyleSheet("font-weight:700;")
        return label

    def _count(self):
        count = len(self.text.toPlainText())
        self.counter.setText(f"{count} / {MAX_TEXT}")
        self.counter.setStyleSheet(f"color:{C['danger'] if count > MAX_TEXT else C['muted']};")

    def _start(self):
        text = self.text.toPlainText().strip()
        if not text:
            self.status.setText("Сначала введи текст")
            return
        if len(text) > MAX_TEXT:
            self.status.setText(f"Слишком длинный текст: максимум {MAX_TEXT} символов")
            return
        self.send.setEnabled(False)
        self.close_button.setEnabled(False)
        self.status.setText("Google генерирует русскую речь…")
        self.worker = _TTSWorker(text, self)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.finished.connect(self._worker_finished)
        self.worker.start()

    def _done(self, pcm, info):
        duration = float(info.get("duration") or (len(pcm) / 48000))
        details = f"Готово: {duration:.1f} сек."
        self.status.setText(details + " Отправляю в комнату…")
        self.play_requested.emit(pcm)
        self.text.clear()
        self.status.setText(details + " Озвучка отправлена участникам.")

    def _failed(self, message):
        self.status.setText(f"Ошибка TTS: {message}")

    def _worker_finished(self):
        self.send.setEnabled(True)
        self.close_button.setEnabled(True)
        self.worker = None

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "TTS-ка", "Дождись завершения генерации речи.")
            event.ignore()
            return
        super().closeEvent(event)
