# -*- mode: python ; coding: utf-8 -*-

from __future__ import annotations

from pathlib import Path

from version import __version__ as app_version

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

def parse_version_tuple(version_text: str) -> tuple[int, int, int, int]:
    parts: list[int] = []
    for raw in version_text.split("."):
        digits = ""
        for ch in raw:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 4:
        parts.append(0)
    return (parts[0], parts[1], parts[2], parts[3])


assets_dir = Path.cwd() / "build_assets"
assets_dir.mkdir(parents=True, exist_ok=True)
version_info_path = assets_dir / "file_version_info.txt"
filevers = parse_version_tuple(app_version)
version_info_path.write_text(
    "\n".join(
        [
            "VSVersionInfo(",
            "  ffi=FixedFileInfo(",
            f"    filevers={filevers},",
            f"    prodvers={filevers},",
            "    mask=0x3f,",
            "    flags=0x0,",
            "    OS=0x40004,",
            "    fileType=0x1,",
            "    subtype=0x0,",
            "    date=(0, 0)",
            "  ),",
            "  kids=[",
            "    StringFileInfo([",
            "      StringTable(",
            "        '040904B0',",
            "        [",
            "          StringStruct('CompanyName', 'ChatList'),",
            "          StringStruct('FileDescription', 'ChatList'),",
            f"          StringStruct('FileVersion', '{app_version}'),",
            "          StringStruct('InternalName', 'ChatListApp'),",
            "          StringStruct('OriginalFilename', 'ChatListApp.exe'),",
            "          StringStruct('ProductName', 'ChatList'),",
            f"          StringStruct('ProductVersion', '{app_version}'),",
            "        ]",
            "      )",
            "    ]),",
            "    VarFileInfo([VarStruct('Translation', [1033, 1200])])",
            "  ]",
            ")",
        ]
    ),
    encoding="utf-8",
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ChatListApp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app_green.ico',
    version=str(version_info_path),
)
