from __future__ import annotations
from app.session import CallSession
from plugins.manager import PluginManager
from ui.windows.main_window import MainWindow


class TrezvonilnikApplication:
    """Собирает сессию, плагины и окно. Вся логика — в CallSession, весь вид — в MainWindow."""

    @staticmethod
    def create_window(nickname: str, host: bool, host_ip: str, room_password: str, room_name: str,
                      settings, store) -> MainWindow:
        plugins = PluginManager()
        plugins.discover()
        session = CallSession(nickname, host, host_ip, room_password, settings, store, plugins, room_name)
        window = MainWindow(session)
        session.start()
        if host:
            window._room(room_name)
        return window
