from __future__ import annotations
import os

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QScrollArea, QSlider, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from config.settings import STREAM_PRESETS
from media.audio.effects import EFFECTS
from media.audio.engine import list_devices
from ui import tween
from ui.theme import C
from ui.widgets.avatar import AvatarWidget
from ui.widgets.base import PillButton, Switch
from ui.widgets.meter import LevelMeter


class Row(QWidget):
    """Строка настройки: слева название + пояснение, справа элемент управления."""

    def __init__(self, title: str, control: QWidget, hint: str = "", parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet("font-weight:600;")
        left.addWidget(t)
        if hint:
            h = QLabel(hint)
            h.setObjectName("Muted")
            h.setWordWrap(True)
            left.addWidget(h)
        lay.addLayout(left, 1)
        lay.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)


class SliderBox(QWidget):
    def __init__(self, lo, hi, value, suffix="%", width=200, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setValue(int(value))
        self.slider.setFixedWidth(width)
        self.label = QLabel()
        self.label.setObjectName("Muted")
        self.label.setFixedWidth(52)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.suffix = suffix
        self.slider.valueChanged.connect(self._upd)
        lay.addWidget(self.slider)
        lay.addWidget(self.label)
        self._upd(self.slider.value())

    def _upd(self, v):
        self.label.setText(f"{v}{self.suffix}")


def _tab(*widgets, stretch=True) -> QScrollArea:
    body = QWidget()
    body.setAttribute(Qt.WA_TranslucentBackground)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(6, 10, 14, 10)
    lay.setSpacing(12)
    for w in widgets:
        lay.addWidget(w)
    lay.addStretch(1)
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(body)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setStyleSheet("QScrollArea{background:transparent;} QScrollArea > QWidget > QWidget{background:transparent;}")
    return area


def _section(text: str) -> QLabel:
    l = QLabel(text.upper())
    l.setObjectName("Section")
    l.setContentsMargins(0, 8, 0, 0)
    return l


class SettingsDialog(QDialog):
    """Все ползунки работают «вживую» (слышно сразу, пока диалог открыт);
    «Отмена» откатывает всё к тому, что было при открытии."""

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.s = session.settings
        self.snapshot = session.snapshot_settings()
        self.setWindowTitle("Настройки")
        self.resize(660, 640)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 18)
        title = QLabel("Настройки")
        title.setObjectName("H1")
        root.addWidget(title)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.inputs, self.outputs, self.dev_error = list_devices()
        self._build_profile()
        self._build_mic()
        self._build_sound()
        self._build_stream()
        self._build_ui()
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = PillButton("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        save = PillButton("Сохранить", "primary", "check")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._saved = False

    # ------------------------------------------------------------------ профиль
    def _build_profile(self):
        card = QWidget()
        lay = QHBoxLayout(card)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(18)
        self.avatar = AvatarWidget(104, self.session.nickname)
        self.avatar.set_image(self.session.avatar_data.get(self.session.my_id))
        lay.addWidget(self.avatar)
        col = QVBoxLayout()
        name = QLabel(self.session.nickname)
        name.setObjectName("H2")
        col.addWidget(name)
        hint = QLabel("PNG, JPG, GIF или WebP. Анимированные GIF/WebP остаются анимированными "
                      "(до 6 секунд), картинка сжимается примерно до 90 КБ.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        col.addWidget(hint)
        row = QHBoxLayout()
        up = PillButton("Загрузить…", "primary", "upload", compact=True)
        up.clicked.connect(self._pick_avatar)
        rm = PillButton("Убрать", "ghost", compact=True)
        rm.clicked.connect(self._clear_avatar)
        row.addWidget(up)
        row.addWidget(rm)
        row.addStretch(1)
        col.addLayout(row)
        self.avatar_msg = QLabel("")
        self.avatar_msg.setStyleSheet(f"color:{C['danger']};")
        col.addWidget(self.avatar_msg)
        lay.addLayout(col, 1)
        note = QLabel("Свою аватарку видят все в комнате. Любому участнику можно поставить аватарку "
                      "только для себя — правый клик по его карточке.")
        note.setObjectName("Faint")
        note.setWordWrap(True)
        self.tabs.addTab(_tab(card, note), "Профиль")

    def _pick_avatar(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать аватарку", "", "Изображения (*.png *.jpg *.jpeg *.gif *.webp *.bmp)")
        if not path:
            return
        try:
            self.session.set_avatar(path)
            self.avatar.set_image(self.session.avatar_data.get(self.session.my_id))
            self.avatar_msg.setText("")
        except Exception as exc:
            self.avatar_msg.setText(f"Не удалось загрузить: {exc}")

    def _clear_avatar(self):
        self.session.set_avatar(None)
        self.avatar.set_image(None)

    # ------------------------------------------------------------------ микрофон
    def _device_combo(self, items, current):
        combo = QComboBox()
        combo.setMinimumWidth(260)
        combo.addItem("По умолчанию", None)
        for idx, name in items:
            combo.addItem(f"{name}", idx)
        i = combo.findData(current)
        combo.setCurrentIndex(max(0, i))
        return combo

    def _build_mic(self):
        s = self.s
        items: list[QWidget] = []
        if self.dev_error:
            warn = QLabel(f"Аудиоустройства недоступны: {self.dev_error}")
            warn.setStyleSheet(f"color:{C['warn']};")
            warn.setWordWrap(True)
            items.append(warn)
        self.mic_dev = self._device_combo(self.inputs, s.mic_index)
        self.mic_dev.currentIndexChanged.connect(lambda: setattr(s, "mic_index", self.mic_dev.currentData()))
        items.append(Row("Микрофон", self.mic_dev))
        items.append(_section("Уровень и порог"))
        self.meter = LevelMeter(s.gate_threshold_db)
        self.meter.threshold_changed.connect(lambda v: (setattr(s, "gate_threshold_db", v), self.session.engine.apply_settings(), self.thr_label.setText(f"{int(v)} дБ")))
        self.thr_label = QLabel(f"{int(s.gate_threshold_db)} дБ")
        self.thr_label.setObjectName("Muted")
        mrow = QWidget()
        ml = QHBoxLayout(mrow)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(self.meter, 1)
        ml.addWidget(self.thr_label)
        items.append(mrow)
        hint = QLabel("Говорите — полоса должна заходить правее маркера. Маркер можно перетаскивать.")
        hint.setObjectName("Muted")
        items.append(hint)
        gate = Switch(s.gate_enabled)
        gate.toggled.connect(lambda v: setattr(s, "gate_enabled", v))
        items.append(Row("Порог чувствительности", gate, "Ниже порога микрофон ничего не передаёт (щелчки, дыхание, вентилятор)."))
        gain = SliderBox(0, 200, s.mic_gain)
        gain.slider.valueChanged.connect(lambda v: setattr(s, "mic_gain", v))
        items.append(Row("Громкость микрофона", gain))
        items.append(_section("Обработка голоса"))
        ns = Switch(s.noise_suppression)
        ns.toggled.connect(lambda v: setattr(s, "noise_suppression", v))
        items.append(Row("Шумоподавление", ns, "Давит ровный шум: вентилятор, гул, шипение. Речь на фоне не убирает."))
        nsl = SliderBox(0, 100, s.ns_strength)
        nsl.slider.valueChanged.connect(lambda v: (setattr(s, "ns_strength", v), self.session.engine.apply_settings()))
        items.append(Row("Сила шумоподавления", nsl))
        ec = Switch(s.echo_suppression)
        ec.toggled.connect(lambda v: setattr(s, "echo_suppression", v))
        items.append(Row("Эхоподавление", ec, "Упрощённое: пока из колонок идёт звук, микрофон приглушается. "
                                              "В наушниках не нужно; на колонках мешает перебивать собеседника."))
        items.append(_section("Войсченджер"))
        self.effect = QComboBox()
        for key, title in EFFECTS.items():
            self.effect.addItem(title, key)
        self.effect.setCurrentIndex(max(0, self.effect.findData(s.voice_effect)))
        self.effect.currentIndexChanged.connect(self._effect_changed)
        items.append(Row("Эффект", self.effect))
        self.intensity = SliderBox(0, 100, s.voice_intensity)
        self.intensity.slider.valueChanged.connect(self._effect_changed)
        items.append(Row("Сила эффекта", self.intensity))
        self.monitor = Switch(self.session.engine.monitor)
        self.monitor.toggled.connect(lambda v: setattr(self.session.engine, "monitor", v))
        items.append(Row("Слышать себя", self.monitor, "Чтобы проверить эффекты и шумодав. Только в наушниках — иначе будет эхо!"))
        self.tabs.addTab(_tab(*items), "Микрофон")

    def _effect_changed(self, *_):
        self.s.voice_effect = self.effect.currentData()
        self.s.voice_intensity = self.intensity.slider.value()
        self.session.engine.apply_settings()

    # ------------------------------------------------------------------ звук
    def _build_sound(self):
        s = self.s
        out = self._device_combo(self.outputs, s.output_index)
        out.currentIndexChanged.connect(lambda: setattr(s, "output_index", out.currentData()))
        vol = SliderBox(0, 200, s.output_volume)
        vol.slider.valueChanged.connect(lambda v: (setattr(s, "output_volume", v), self.session.engine.apply_settings()))
        sfx = SliderBox(0, 150, s.sfx_volume)
        sfx.slider.valueChanged.connect(lambda v: (setattr(s, "sfx_volume", v), self.session.engine.apply_settings()))
        mus = SliderBox(0, 150, s.music_volume)
        mus.slider.valueChanged.connect(lambda v: (setattr(s, "music_volume", v), self.session.engine.apply_settings()))
        self.tabs.addTab(_tab(Row("Устройство вывода", out), Row("Общая громкость", vol),
                              Row("Громкость саундпада", sfx, "Только у вас; громкость отдельного звука задаётся в его настройках."),
                              Row("Громкость музыки", mus)), "Звук")

    # ------------------------------------------------------------------ демонстрация
    def _build_stream(self):
        s = self.s
        self.preset = QComboBox()
        for key, p in STREAM_PRESETS.items():
            self.preset.addItem(p["title"], key)
        self.preset.addItem("Свои параметры", "custom")
        self.preset.setCurrentIndex(max(0, self.preset.findData(s.stream_preset if s.stream_preset in STREAM_PRESETS else "custom")))
        self.fps = QSpinBox(); self.fps.setRange(5, 60); self.fps.setValue(s.video_fps); self.fps.setSuffix(" fps")
        self.width_ = QComboBox()
        for w in (480, 640, 960, 1280, 1600, 1920):
            self.width_.addItem(f"{w} px", w)
        self.width_.setCurrentIndex(max(0, self.width_.findData(s.video_width)))
        self.kbps = QSpinBox(); self.kbps.setRange(300, 20000); self.kbps.setSingleStep(250); self.kbps.setValue(s.video_kbps); self.kbps.setSuffix(" кбит/с")
        self.preset.currentIndexChanged.connect(self._preset_changed)
        for w in (self.fps, self.kbps):
            w.valueChanged.connect(self._custom)
        self.width_.currentIndexChanged.connect(self._custom)
        note = QLabel("Видео передаётся JPEG-кадрами и обходится дорого: каждому зрителю хост-реле отдаёт столько же. "
                      "Чем выше битрейт, тем выше шанс потерять кадр на UDP. Для 3–4 зрителей обычно хватает «Обычного».")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.tabs.addTab(_tab(Row("Пресет", self.preset), Row("Частота кадров", self.fps), Row("Ширина кадра", self.width_),
                              Row("Целевой битрейт", self.kbps, "Качество JPEG подстраивается под него автоматически."), note), "Демонстрация")

    def _preset_changed(self):
        key = self.preset.currentData()
        if key in STREAM_PRESETS:
            p = STREAM_PRESETS[key]
            self._block(True)
            self.fps.setValue(p["fps"]); self.kbps.setValue(p["kbps"]); self.width_.setCurrentIndex(self.width_.findData(p["width"]))
            self._block(False)
            self.s.apply_preset(key)

    def _block(self, on):
        for w in (self.fps, self.kbps, self.width_):
            w.blockSignals(on)

    def _custom(self):
        self.s.stream_preset = "custom"
        self.s.video_fps, self.s.video_kbps, self.s.video_width = self.fps.value(), self.kbps.value(), self.width_.currentData()
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(self.preset.findData("custom"))
        self.preset.blockSignals(False)

    # ------------------------------------------------------------------ интерфейс
    def _build_ui(self):
        s = self.s
        anim = Switch(s.animations)
        anim.toggled.connect(lambda v: (setattr(s, "animations", v), tween.set_enabled(v)))
        toasts = Switch(s.toasts)
        toasts.toggled.connect(lambda v: setattr(s, "toasts", v))
        react = Switch(s.reactions)
        react.toggled.connect(lambda v: setattr(s, "reactions", v))
        self.tabs.addTab(_tab(Row("Анимации", anim, "Выключите, если интерфейс тормозит или анимации раздражают."),
                              Row("Уведомления", toasts, "Заходы/выходы, начало трансляций, музыка."),
                              Row("Показывать чужие реакции", react)), "Интерфейс")

    # ------------------------------------------------------------------ жизненный цикл
    def _poll(self):
        self.meter.set_level(self.session.engine.input_level_db)

    def _save(self):
        self._saved = True
        self.timer.stop()
        self.session.engine.monitor = False
        self.session.apply_settings(previous=self.snapshot)
        self.accept()

    def reject(self):
        if not self._saved:
            self.session.restore_settings(self.snapshot)
            tween.set_enabled(self.snapshot.animations)
        self.session.engine.monitor = False
        self.timer.stop()
        super().reject()
