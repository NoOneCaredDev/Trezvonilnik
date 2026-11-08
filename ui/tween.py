"""Твины. Одна точка входа — tween(); выключатель set_enabled(False) убирает анимации везде."""
from __future__ import annotations
from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QObject, QPropertyAnimation, QTimer,
                            QVariantAnimation)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

EASE = QEasingCurve
_enabled = True


def set_enabled(on: bool) -> None:
    global _enabled
    _enabled = bool(on)


def enabled() -> bool:
    return _enabled


def _curve(easing) -> QEasingCurve:
    return easing if isinstance(easing, QEasingCurve) else QEasingCurve(easing)


def tween(target: QObject, prop: str, end, ms: int = 220, easing=EASE.OutCubic, start=None, on_done=None):
    """Плавно меняет Qt-свойство. Новый твин того же свойства перебивает старый (без накопления)."""
    name = prop.encode()
    store: dict = target.__dict__.setdefault("_tweens", {})
    old = store.pop(name, None)
    if old is not None:
        old.stop()
        old.deleteLater()
    if not _enabled or ms <= 0:
        target.setProperty(prop, end)
        if on_done:
            QTimer.singleShot(0, on_done)
        return None
    anim = QPropertyAnimation(target, name, target)
    anim.setDuration(ms)
    anim.setEasingCurve(_curve(easing))
    if start is not None:
        anim.setStartValue(start)
    anim.setEndValue(end)

    def finished():
        if store.get(name) is anim:
            store.pop(name, None)
        anim.deleteLater()
        if on_done:
            on_done()
    anim.finished.connect(finished)
    store[name] = anim
    anim.start()
    return anim


def value_tween(parent: QObject, start: float, end: float, ms: int, on_update, easing=EASE.OutCubic, on_done=None):
    """Твин без свойства: дёргает on_update(значение)."""
    if not _enabled or ms <= 0:
        on_update(end)
        if on_done:
            QTimer.singleShot(0, on_done)
        return None
    anim = QVariantAnimation(parent)
    anim.setStartValue(float(start))
    anim.setEndValue(float(end))
    anim.setDuration(ms)
    anim.setEasingCurve(_curve(easing))
    anim.valueChanged.connect(lambda v: on_update(float(v)))
    if on_done:
        anim.finished.connect(on_done)
    anim.finished.connect(anim.deleteLater)
    anim.start()
    return anim


def fade_in(widget: QWidget, ms: int = 260, on_done=None):
    """Появление через временный opacity-эффект (после окончания эффект снимается — он дорогой)."""
    if not _enabled:
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(0.0)
    widget.setGraphicsEffect(effect)

    def finish():
        if widget.graphicsEffect() is effect:
            widget.setGraphicsEffect(None)
        if on_done:
            on_done()
    tween(effect, "opacity", 1.0, ms, EASE.OutCubic, on_done=finish)


def fade_out(widget: QWidget, ms: int = 200, on_done=None):
    if not _enabled:
        if on_done:
            on_done()
        return
    effect = QGraphicsOpacityEffect(widget)
    effect.setOpacity(1.0)
    widget.setGraphicsEffect(effect)
    tween(effect, "opacity", 0.0, ms, EASE.InCubic, on_done=on_done)


def shake(widget: QWidget, amplitude: int = 7):
    """Короткая «тряска» — для ошибки в поле."""
    if not _enabled:
        return
    x0 = widget.x()
    anim = QVariantAnimation(widget)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setDuration(380)

    def step(t):
        import math
        widget.move(x0 + int(math.sin(float(t) * 18) * amplitude * (1 - float(t))), widget.y())
    anim.valueChanged.connect(step)
    anim.finished.connect(lambda: widget.move(x0, widget.y()))
    anim.finished.connect(anim.deleteLater)
    anim.start(QAbstractAnimation.KeepWhenStopped)
