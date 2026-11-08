"""Единственное место, где живут цвета, шрифты и глобальный QSS."""
from __future__ import annotations
from PySide6.QtGui import QColor, QFont, QFontDatabase

C = {
    "bg0": "#080d10", "bg1": "#0e151a", "bg2": "#141e24", "bg3": "#1b2831", "bg4": "#243541",
    "border": "#1f2f38", "border2": "#2c424e",
    "text": "#e9f2f5", "muted": "#7d95a1", "faint": "#51666f",
    "accent": "#5ef2c4", "accent2": "#4cc9f0", "accent_dim": "#1c5a4d",
    "danger": "#ff5d6c", "warn": "#ffb454", "host": "#ff9a6b", "live": "#ff4d6d", "ok": "#6df0a0",
}

FONT_UI = ["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Noto Sans", "DejaVu Sans"]
FONT_EMOJI = ["Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji"]


def qc(name: str, alpha: float = 1.0) -> QColor:
    color = QColor(C.get(name, name))
    color.setAlphaF(alpha)
    return color


def mix(a: str | QColor, b: str | QColor, t: float) -> QColor:
    ca = a if isinstance(a, QColor) else qc(a)
    cb = b if isinstance(b, QColor) else qc(b)
    t = max(0.0, min(1.0, t))
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t),
                  round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t),
                  round(ca.alpha() + (cb.alpha() - ca.alpha()) * t))


_WEIGHTS = {300: QFont.Light, 400: QFont.Normal, 500: QFont.Medium, 600: QFont.DemiBold,
            700: QFont.Bold, 800: QFont.ExtraBold, 900: QFont.Black}


def ui_font(size: float = 10, weight=400) -> QFont:
    f = QFont()
    f.setFamilies(FONT_UI)
    f.setPointSizeF(size)
    f.setWeight(_WEIGHTS.get(weight, weight) if isinstance(weight, int) else weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


def emoji_font(size: float = 16) -> QFont:
    f = QFont()
    f.setFamilies(FONT_EMOJI + FONT_UI)
    f.setPointSizeF(size)
    return f


def avatar_color(name: str) -> QColor:
    """Стабильный цвет аватарки-заглушки по нику."""
    h = 0
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFF
    return QColor.fromHsv(h % 360, 150, 190)


def stylesheet() -> str:
    c = C
    fam = ", ".join(f"'{f}'" for f in FONT_UI)
    return f"""
    * {{ font-family: {fam}; font-size: 10pt; color: {c['text']}; outline: 0; }}
    QWidget#Root, QDialog, QMainWindow {{ background: {c['bg0']}; }}
    QLabel {{ background: transparent; }}
    QLabel#Muted {{ color: {c['muted']}; }}
    QLabel#Faint {{ color: {c['faint']}; }}
    QLabel#H1 {{ font-size: 20pt; font-weight: 800; }}
    QLabel#H2 {{ font-size: 12pt; font-weight: 700; }}
    QLabel#Section {{ font-size: 8.5pt; font-weight: 800; color: {c['muted']}; letter-spacing: 1.4px; }}
    QToolTip {{ background: {c['bg3']}; color: {c['text']}; border: 1px solid {c['border2']};
               border-radius: 6px; padding: 5px 8px; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit {{
        background: {c['bg1']}; border: 1px solid {c['border']}; border-radius: 10px;
        padding: 8px 11px; selection-background-color: {c['accent_dim']}; }}
    QLineEdit:hover, QSpinBox:hover, QComboBox:hover {{ border-color: {c['border2']}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {c['accent']}; }}
    QLineEdit:disabled, QComboBox:disabled {{ color: {c['faint']}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox::down-arrow {{ image: none; width: 0; height: 0; border-left: 4px solid transparent;
                            border-right: 4px solid transparent; border-top: 5px solid {c['muted']}; margin-right: 10px; }}
    QComboBox QAbstractItemView {{ background: {c['bg2']}; border: 1px solid {c['border2']}; border-radius: 10px;
                                  padding: 4px; selection-background-color: {c['bg4']}; }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; }}

    QSlider::groove:horizontal {{ background: {c['bg4']}; height: 6px; border-radius: 3px; }}
    QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 3px; }}
    QSlider::handle:horizontal {{ background: {c['text']}; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px; }}
    QSlider::handle:horizontal:hover {{ background: {c['accent']}; }}
    QSlider::groove:vertical {{ background: {c['bg4']}; width: 6px; border-radius: 3px; }}
    QSlider::add-page:vertical {{ background: {c['accent']}; border-radius: 3px; }}
    QSlider::handle:vertical {{ background: {c['text']}; height: 16px; width: 16px; margin: 0 -5px; border-radius: 8px; }}

    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {c['bg4']}; border-radius: 3px; min-height: 30px; margin: 0 2px; }}
    QScrollBar::handle:vertical:hover {{ background: {c['border2']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 10px; background: transparent; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {c['bg4']}; border-radius: 3px; min-width: 30px; }}

    QMenu {{ background: {c['bg2']}; border: 1px solid {c['border2']}; border-radius: 12px; padding: 6px; }}
    QMenu::item {{ padding: 8px 26px 8px 14px; border-radius: 8px; }}
    QMenu::item:selected {{ background: {c['bg4']}; }}
    QMenu::item:disabled {{ color: {c['faint']}; }}
    QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}

    QTabWidget::pane {{ border: none; }}
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{ background: transparent; color: {c['muted']}; padding: 9px 16px; margin-right: 2px;
                   border-radius: 9px; font-weight: 600; }}
    QTabBar::tab:hover {{ color: {c['text']}; background: {c['bg2']}; }}
    QTabBar::tab:selected {{ color: {c['text']}; background: {c['bg3']}; }}

    QListWidget {{ background: transparent; border: none; }}
    QListWidget::item {{ border-radius: 9px; padding: 8px; }}
    QListWidget::item:selected {{ background: {c['bg4']}; }}
    QListWidget::item:hover {{ background: {c['bg3']}; }}
    QProgressBar {{ background: {c['bg4']}; border: none; border-radius: 3px; max-height: 6px; text-align: center; }}
    QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}
    """


def install_fonts_hint(app) -> None:
    app.setFont(ui_font(10))


def dark_palette():
    """Палитра для нативных диалогов (QMessageBox, QFileDialog), которые QSS не покрывает целиком."""
    from PySide6.QtGui import QPalette
    pal = QPalette()
    roles = {QPalette.Window: "bg0", QPalette.WindowText: "text", QPalette.Base: "bg1", QPalette.AlternateBase: "bg2",
             QPalette.Text: "text", QPalette.Button: "bg3", QPalette.ButtonText: "text", QPalette.ToolTipBase: "bg3",
             QPalette.ToolTipText: "text", QPalette.Highlight: "accent_dim", QPalette.HighlightedText: "text",
             QPalette.PlaceholderText: "faint"}
    for role, name in roles.items():
        pal.setColor(role, qc(name))
    return pal
