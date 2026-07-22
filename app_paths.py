from __future__ import annotations

import os
import sys
from pathlib import Path


def get_app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _is_installed_under_program_files(path: Path) -> bool:
    candidates = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if _is_inside(path, Path(candidate)):
            return True
    return False


def get_app_data_dir(app_name: str = "ChatList") -> Path:
    base_dir = get_app_base_dir()
    if not getattr(sys, "frozen", False):
        return base_dir

    if not _is_installed_under_program_files(base_dir):
        return base_dir

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / app_name

    return Path.home() / "AppData" / "Local" / app_name


def unique_paths(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except Exception:
            resolved = path
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result
