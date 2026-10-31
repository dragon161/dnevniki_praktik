"""Совместимость PySide6 (Qt 6, Windows 10+) и PySide2 (Qt 5.15, работает на Windows 7)."""
from __future__ import annotations

try:  # Qt 6
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    from PySide6.QtGui import QAction  # noqa: F401
    QT_API = "PySide6"
except ImportError:  # Qt 5 — для Windows 7
    from PySide2 import QtCore, QtGui, QtWidgets  # noqa: F401  # type: ignore
    from PySide2.QtWidgets import QAction  # noqa: F401
    QT_API = "PySide2"


def exec_(obj):
    """dialog.exec() / app.exec() — в PySide2 метод называется exec_()."""
    fn = getattr(obj, "exec", None) or getattr(obj, "exec_")
    return fn()


def enable_high_dpi() -> None:
    """В Qt 5 масштабирование под HiDPI нужно включать до создания QApplication."""
    if QT_API == "PySide2":
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
