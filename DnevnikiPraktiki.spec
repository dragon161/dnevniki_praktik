# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: pyinstaller --noconfirm --clean DnevnikiPraktiki.spec
block_cipher = None

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("templates/diary_template.docx", "templates")],
    hiddenimports=["openpyxl", "docx"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6", "tkinter", "unittest", "pydoc", "PySide2.QtNetwork", "PySide2.QtQml",
              "PySide2.QtQuick", "PySide2.QtWebEngineCore", "PySide2.QtMultimedia",
              "PySide2.Qt3DCore", "PySide2.QtSql", "PySide2.QtXml"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="DnevnikiPraktiki",
    debug=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
)
