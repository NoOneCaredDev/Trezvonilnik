"""Векторные иконки: рисуются QPainter-ом на сетке 24×24, поэтому чёткие на любом масштабе и DPI,
красятся в любой цвет (в том числе твином) и не требуют файлов."""
from __future__ import annotations
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF


def _line(p, x1, y1, x2, y2):
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))


def _dot(p, x, y, r, color):
    p.setBrush(color)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(x, y), r, r)
    p.setBrush(Qt.NoBrush)


def _poly(p, pts, fill=None):
    poly = QPolygonF([QPointF(*pt) for pt in pts])
    if fill is not None:
        p.setBrush(fill)
    p.drawPolygon(poly)
    p.setBrush(Qt.NoBrush)


def _draw(p: QPainter, name: str, c: QColor):
    if name == "mic":
        p.drawRoundedRect(QRectF(9, 2.5, 6, 11.5), 3, 3)
        path = QPainterPath(QPointF(5.5, 11))
        path.arcTo(QRectF(5.5, 6.5, 13, 11), 180, 180)
        p.drawPath(path)
        _line(p, 12, 17.5, 12, 21); _line(p, 8.5, 21, 15.5, 21)
    elif name == "headphones":
        path = QPainterPath(QPointF(4, 15))
        path.arcTo(QRectF(4, 3.5, 16, 16), 180, -180)
        p.drawPath(path)
        p.drawRoundedRect(QRectF(3, 13, 4.5, 7.5), 2, 2)
        p.drawRoundedRect(QRectF(16.5, 13, 4.5, 7.5), 2, 2)
    elif name == "screen":
        p.drawRoundedRect(QRectF(3, 4, 18, 12.5), 2.5, 2.5)
        _line(p, 8.5, 20.5, 15.5, 20.5); _line(p, 12, 16.5, 12, 20.5)
    elif name == "smile":
        p.drawEllipse(QPointF(12, 12), 9, 9)
        path = QPainterPath(QPointF(8, 14))
        path.quadTo(12, 18.5, 16, 14)
        p.drawPath(path)
        _dot(p, 9, 9.5, 1.15, c); _dot(p, 15, 9.5, 1.15, c)
    elif name == "gear":
        p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        p.drawEllipse(QPointF(12, 12), 7, 7)
        for i in range(8):
            a = i * math.pi / 4
            _line(p, 12 + 7 * math.cos(a), 12 + 7 * math.sin(a), 12 + 9.8 * math.cos(a), 12 + 9.8 * math.sin(a))
    elif name == "music":
        p.drawEllipse(QPointF(7.5, 18), 3, 2.6)
        p.drawEllipse(QPointF(17, 16), 3, 2.6)
        _line(p, 10.5, 18, 10.5, 5.5); _line(p, 20, 16, 20, 3.5); _line(p, 10.5, 5.5, 20, 3.5)
    elif name == "wheel":
        p.drawEllipse(QPointF(12, 13), 8.5, 8.5)
        for i in range(4):
            a = i * math.pi / 4
            _line(p, 12 - 8.5 * math.cos(a), 13 - 8.5 * math.sin(a), 12 + 8.5 * math.cos(a), 13 + 8.5 * math.sin(a))
        _dot(p, 12, 13, 1.8, c)
        _poly(p, [(12, 3.6), (9.6, 0.6), (14.4, 0.6)], c)
    elif name == "pad":
        for x, y in ((3.5, 3.5), (13.5, 3.5), (3.5, 13.5), (13.5, 13.5)):
            p.drawRoundedRect(QRectF(x, y, 7, 7), 2, 2)
    elif name == "plus":
        _line(p, 12, 5, 12, 19); _line(p, 5, 12, 19, 12)
    elif name == "close":
        _line(p, 6, 6, 18, 18); _line(p, 18, 6, 6, 18)
    elif name == "check":
        path = QPainterPath(QPointF(5, 12.5)); path.lineTo(10, 17.5); path.lineTo(19, 7)
        p.drawPath(path)
    elif name == "play":
        _poly(p, [(7, 4.5), (19.5, 12), (7, 19.5)], c)
    elif name == "pause":
        p.setBrush(c)
        p.drawRoundedRect(QRectF(6, 4.5, 4, 15), 1.2, 1.2); p.drawRoundedRect(QRectF(14, 4.5, 4, 15), 1.2, 1.2)
        p.setBrush(Qt.NoBrush)
    elif name == "skip":
        _poly(p, [(5, 5), (15.5, 12), (5, 19)], c)
        p.setBrush(c); p.drawRoundedRect(QRectF(17, 5, 3, 14), 1, 1); p.setBrush(Qt.NoBrush)
    elif name == "stop":
        p.setBrush(c); p.drawRoundedRect(QRectF(6, 6, 12, 12), 2.5, 2.5); p.setBrush(Qt.NoBrush)
    elif name == "volume":
        _poly(p, [(4, 9.5), (8, 9.5), (13, 5), (13, 19), (8, 14.5), (4, 14.5)], c)
        path = QPainterPath(QPointF(16, 9)); path.quadTo(18.5, 12, 16, 15); p.drawPath(path)
        path = QPainterPath(QPointF(18.5, 6.5)); path.quadTo(23, 12, 18.5, 17.5); p.drawPath(path)
    elif name == "eye":
        path = QPainterPath(QPointF(2, 12)); path.quadTo(12, 1, 22, 12); path.quadTo(12, 23, 2, 12)
        p.drawPath(path); p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
    elif name == "crown":
        _poly(p, [(4, 18), (3.5, 8), (8.5, 12.5), (12, 5.5), (15.5, 12.5), (20.5, 8), (20, 18)], c)
    elif name == "shield":
        path = QPainterPath(QPointF(12, 3)); path.lineTo(20, 6); path.lineTo(20, 12)
        path.quadTo(20, 18.5, 12, 21.5); path.quadTo(4, 18.5, 4, 12); path.lineTo(4, 6); path.closeSubpath()
        p.drawPath(path)
    elif name == "trash":
        _line(p, 4, 7, 20, 7); _line(p, 9.5, 7, 9.5, 4); _line(p, 14.5, 7, 14.5, 4); _line(p, 9.5, 4, 14.5, 4)
        p.drawRoundedRect(QRectF(6, 7, 12, 13.5), 2, 2); _line(p, 10, 11, 10, 17); _line(p, 14, 11, 14, 17)
    elif name == "expand":
        for (x1, y1, x2, y2, x3, y3) in ((4, 9, 4, 4, 9, 4), (15, 4, 20, 4, 20, 9), (20, 15, 20, 20, 15, 20), (9, 20, 4, 20, 4, 15)):
            path = QPainterPath(QPointF(x1, y1)); path.lineTo(x2, y2); path.lineTo(x3, y3); p.drawPath(path)
    elif name == "search":
        p.drawEllipse(QPointF(10.5, 10.5), 6.5, 6.5); _line(p, 15.5, 15.5, 21, 21)
    elif name == "upload":
        _line(p, 12, 16, 12, 4); path = QPainterPath(QPointF(7, 9)); path.lineTo(12, 4); path.lineTo(17, 9); p.drawPath(path)
        _line(p, 4, 20, 20, 20)
    elif name == "user":
        p.drawEllipse(QPointF(12, 8), 4, 4)
        path = QPainterPath(QPointF(4, 21)); path.quadTo(12, 10.5, 20, 21); p.drawPath(path)
    elif name == "dice":
        p.drawRoundedRect(QRectF(3.5, 3.5, 17, 17), 4, 4)
        for x, y in ((8.5, 8.5), (15.5, 8.5), (12, 12), (8.5, 15.5), (15.5, 15.5)):
            _dot(p, x, y, 1.3, c)
    elif name == "pin":
        _poly(p, [(9, 3), (15, 3), (14, 9), (18, 13), (6, 13), (10, 9)], c)
        _line(p, 12, 13, 12, 21)
    elif name == "lock":
        p.drawRoundedRect(QRectF(5, 11, 14, 10), 2.5, 2.5)
        path = QPainterPath(QPointF(8, 11)); path.lineTo(8, 8); path.arcTo(QRectF(8, 3.5, 8, 9), 180, -180); path.lineTo(16, 11)
        p.drawPath(path)
    elif name == "queue":
        for y in (6, 12, 18):
            _line(p, 4, y, 15, y)
        _poly(p, [(17.5, 15), (21.5, 18), (17.5, 21)], c)
    elif name == "arrow-left":
        path = QPainterPath(QPointF(14, 5)); path.lineTo(7, 12); path.lineTo(14, 19); p.drawPath(path)


def draw_icon(p: QPainter, name: str, rect: QRectF, color: QColor, width: float = 1.9, slash: QColor | None = None):
    p.save()
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    p.translate(rect.x(), rect.y())
    p.scale(rect.width() / 24.0, rect.height() / 24.0)
    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _draw(p, name, color)
    if slash is not None:
        p.setPen(QPen(slash, width + 0.8, Qt.SolidLine, Qt.RoundCap))
        _line(p, 4, 3.5, 20, 20.5)
    p.restore()
