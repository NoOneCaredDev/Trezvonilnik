import sys
import logging
from logging.handlers import RotatingFileHandler

from app.paths import data_dir


def configure_logging() -> None:
    """Write diagnostics both to the VS Code terminal and a persistent log."""
    log_dir = data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_dir / "trezvonilnik.log", maxBytes=2_000_000,
        backupCount=3, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from app.application import TrezvonilnikApplication
from app.session import SessionError
from config.settings import SettingsStore
from ui import theme, tween
from ui.windows.login import LoginDialog
from ui.winutil import enable_dark_titlebar


def main() -> int:
    configure_logging()
    logging.info("Запуск Трезвонильника")
    app = QApplication(sys.argv)
    app.setApplicationName("Трезвонильник")
    app.setStyle("Fusion")
    app.setPalette(theme.dark_palette())
    app.setStyleSheet(theme.stylesheet())
    app.setFont(theme.ui_font(10))
    store = SettingsStore()
    settings = store.load()
    tween.set_enabled(settings.animations)
    while True:
        login = LoginDialog(settings)
        enable_dark_titlebar(login)
        if login.exec() != QDialog.Accepted:
            return 0
        store.save(settings)
        try:
            window = TrezvonilnikApplication.create_window(login.nickname, login.is_host, login.host_ip,
                                                           login.room_password, login.room_name, settings, store)
        except SessionError as exc:
            QMessageBox.critical(None, "Трезвонильник", str(exc))
            continue
        window.show()
        return app.exec()


if __name__ == "__main__":
    sys.exit(main())
