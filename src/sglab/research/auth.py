from __future__ import annotations

from pathlib import Path
import os
import shutil


def director_home(application_data: Path) -> Path:
    return application_data.resolve() / "director" / "codex-home"


def director_sqlite_home(application_data: Path) -> Path:
    return application_data.resolve() / "director" / "codex-sqlite-home"


def director_work(application_data: Path) -> Path:
    return application_data.resolve() / "director" / "codex-work"


def prepare_private_directories(application_data: Path) -> tuple[Path, Path, Path]:
    home = director_home(application_data)
    sqlite_home = director_sqlite_home(application_data)
    work = director_work(application_data)
    if not all(path.is_absolute() for path in (home, sqlite_home, work)):
        raise ValueError("Codex private directories must be absolute")
    if len({home, sqlite_home, work}) != 3:
        raise ValueError("Codex private directories must be distinct")
    for directory in (home, sqlite_home, work):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
    return home, sqlite_home, work


def import_authorized_auth(source_codex_home: Path, application_data: Path) -> Path:
    """Copy only auth.json after an explicit operator command."""

    source_home = source_codex_home.expanduser().resolve()
    source = source_home / "auth.json"
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"authorized source has no regular auth.json: {source_home}")
    home, _, _ = prepare_private_directories(application_data)
    destination = home / "auth.json"
    temporary = home / "auth.json.importing"
    with source.open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    destination.chmod(0o600)
    return destination


def auth_is_imported(application_data: Path) -> bool:
    path = director_home(application_data) / "auth.json"
    return path.is_file() and not path.is_symlink()
