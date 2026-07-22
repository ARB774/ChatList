from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from version import __version__


def pick_latest_exe(candidates: list[Path]) -> Path:
    existing = [path for path in candidates if path.exists()]
    if not existing:
        raise FileNotFoundError("Не найден ChatListApp.exe в dist или dist_new.")
    return max(existing, key=lambda path: path.stat().st_mtime)


def find_iscc() -> Path:
    from_path = shutil.which("ISCC.exe")
    if from_path:
        return Path(from_path)

    candidates: list[Path] = []
    for env_name in ["LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"]:
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        candidates.append(Path(env_value) / "Programs" / "Inno Setup 6" / "ISCC.exe")
        candidates.append(Path(env_value) / "Inno Setup 6" / "ISCC.exe")

    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(
        "Не найден ISCC.exe. Установите Inno Setup 6 или добавьте ISCC.exe в стандартный путь."
    )


def write_installer_defines(
    defines_path: Path,
    *,
    exe_path: Path,
    output_dir: Path,
) -> None:
    installer_base_name = f"ChatListApp_Setup_{__version__}"
    lines = [
        f'#define MyAppName "ChatList"',
        f'#define MyAppVersion "{__version__}"',
        f'#define MyAppExeSource "{exe_path}"',
        f'#define MyOutputDir "{output_dir}"',
        f'#define MyInstallerBaseName "{installer_base_name}"',
    ]
    defines_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    root_dir = Path(__file__).resolve().parent
    source_exe = pick_latest_exe(
        [
            root_dir / "dist" / "ChatListApp.exe",
            root_dir / "dist_new" / "ChatListApp.exe",
            root_dir / "dist_new" / "ChatListApp_new.exe",
            root_dir / "dist_version_test" / "ChatListApp.exe",
        ]
    )
    iscc_path = find_iscc()
    assets_dir = root_dir / "build_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    release_dir = root_dir / "release"
    release_dir.mkdir(parents=True, exist_ok=True)
    defines_path = assets_dir / "installer_defines.iss"
    write_installer_defines(defines_path, exe_path=source_exe, output_dir=release_dir)

    installer_script = root_dir / "ChatListInstaller.iss"
    subprocess.run(
        [str(iscc_path), str(installer_script)],
        check=True,
        cwd=root_dir,
    )
    target_path = release_dir / f"ChatListApp_Setup_{__version__}.exe"
    print(str(target_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
