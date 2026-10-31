# -*- mode: python ; coding: utf-8 -*-
# PyInstaller: pyinstaller --noconfirm --clean DnevnikiPraktiki.spec
import glob
import os
import struct
import sys

block_cipher = None


def ucrt_dlls():
    """Universal C Runtime (ucrtbase.dll + api-ms-win-crt-*.dll) from the Windows 10 SDK.

    Bundling it app-locally is supported by Microsoft and removes the need for
    the KB2999226 update on Windows 7 / 8.1. On Windows 10+ the system copy is used.
    """
    if sys.platform != "win32":
        return []
    arch = "x64" if struct.calcsize("P") == 8 else "x86"
    roots = [os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
             os.environ.get("ProgramFiles", r"C:\Program Files")]
    dirs = []
    for root in roots:
        base = os.path.join(root, "Windows Kits", "10", "Redist")
        dirs += sorted(glob.glob(os.path.join(base, "10.*", "ucrt", "DLLs", arch)), reverse=True)
        dirs += glob.glob(os.path.join(base, "ucrt", "DLLs", arch))
    for d in dirs:
        files = glob.glob(os.path.join(d, "*.dll"))
        if any(os.path.basename(f).lower() == "ucrtbase.dll" for f in files):
            print("UCRT bundled from", d, "(%d files)" % len(files))
            return [(f, ".") for f in files]
    print("WARNING: Windows 10 SDK UCRT not found - exe will need KB2999226 on Windows 7")
    return []


a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=ucrt_dlls(),
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
