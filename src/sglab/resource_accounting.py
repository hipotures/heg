from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any
import os
import stat


PRESERVED_ARTIFACTS = "preserved_artifacts"
RUNTIME_SCRATCH = "runtime_scratch"
CREDENTIAL_MATERIAL = "credential_material"
LOGS = "logs"
RESOURCE_CATEGORIES = (
    PRESERVED_ARTIFACTS,
    RUNTIME_SCRATCH,
    CREDENTIAL_MATERIAL,
    LOGS,
)

DEFAULT_MAX_PRESERVED_ARTIFACT_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_RUNTIME_SCRATCH_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_SINGLE_PRESERVED_ARTIFACT_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_SINGLE_RUNTIME_FILE_BYTES = 256 * 1024 * 1024


class ResourceAccountingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceFile:
    category: str
    relative_path: str
    apparent_bytes: int
    allocated_bytes: int
    sparse: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "relative_path": self.relative_path,
            "apparent_bytes": self.apparent_bytes,
            "allocated_bytes": self.allocated_bytes,
            "sparse": self.sparse,
        }


@dataclass(slots=True)
class CategoryAccounting:
    apparent_bytes: int = 0
    allocated_bytes: int = 0
    file_count: int = 0
    sparse_file_count: int = 0
    largest_files: list[ResourceFile] = field(default_factory=list)
    largest_directories: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "apparent_bytes": self.apparent_bytes,
            "allocated_bytes": self.allocated_bytes,
            "file_count": self.file_count,
            "sparse_file_count": self.sparse_file_count,
            "largest_files": [value.as_dict() for value in self.largest_files],
            "largest_directories": self.largest_directories,
        }


@dataclass(frozen=True, slots=True)
class ResourceAccounting:
    sampled_at_monotonic: float
    elapsed_seconds: float
    entry_count: int
    hardlink_duplicates: int
    symlink_count: int
    escaping_symlinks: tuple[str, ...]
    categories: dict[str, CategoryAccounting]
    files: tuple[ResourceFile, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "entry_count": self.entry_count,
            "hardlink_duplicates": self.hardlink_duplicates,
            "symlink_count": self.symlink_count,
            "escaping_symlinks": list(self.escaping_symlinks),
            "categories": {
                name: value.as_dict()
                for name, value in self.categories.items()
            },
        }


def resource_category(relative_path: Path) -> str:
    """Assign one stable ownership category without inspecting file contents."""

    parts = relative_path.parts
    name = relative_path.name.lower()
    if name in {"auth.json", "auth.json.importing"}:
        return CREDENTIAL_MATERIAL
    if parts and parts[0] in {"arms", "attempts", "resource-diagnostics"}:
        return PRESERVED_ARTIFACTS
    if parts and parts[0] == "runtime-groups":
        lowered = {part.lower() for part in parts}
        if (
            "wire" in lowered
            or "stderr" in lowered
            or name.endswith(".log")
            or name.endswith(".jsonl") and "sessions" not in lowered
        ):
            return LOGS
        return RUNTIME_SCRATCH
    if name.endswith((".log", ".jsonl")):
        return LOGS
    return RUNTIME_SCRATCH


def _safe_label(relative_path: Path, category: str) -> str:
    if category == CREDENTIAL_MATERIAL:
        return "credential_material/[redacted]"
    return relative_path.as_posix()


def account_execution_root(
    root: Path,
    *,
    max_entries: int = 20_000,
    max_seconds: float = 2.0,
    largest_n: int = 8,
) -> ResourceAccounting:
    """Account one private execution tree with lstat and no link traversal."""

    if max_entries < 1 or max_seconds <= 0 or largest_n < 1:
        raise ValueError("accounting bounds must be positive")
    started = monotonic()
    root = root.absolute()
    try:
        root_stat = root.lstat()
    except OSError as error:
        raise ResourceAccountingError(
            f"execution root is inaccessible: {type(error).__name__}"
        ) from error
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise ResourceAccountingError("execution root must be a regular directory")

    categories = {name: CategoryAccounting() for name in RESOURCE_CATEGORIES}
    files: dict[str, list[ResourceFile]] = {
        name: [] for name in RESOURCE_CATEGORIES
    }
    directory_totals: dict[tuple[str, str], list[int]] = {}
    seen_inodes: set[tuple[int, int]] = set()
    escaping_symlinks: list[str] = []
    hardlink_duplicates = 0
    symlink_count = 0
    entry_count = 0
    stack = [root]

    while stack:
        if monotonic() - started > max_seconds:
            raise ResourceAccountingError("resource traversal time limit exceeded")
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as error:
            relative = directory.relative_to(root).as_posix() or "."
            raise ResourceAccountingError(
                f"inaccessible directory: {relative}: {type(error).__name__}"
            ) from error
        entries.sort(key=lambda entry: entry.name)
        for entry in entries:
            entry_count += 1
            if entry_count > max_entries:
                raise ResourceAccountingError("resource traversal entry limit exceeded")
            path = Path(entry.path)
            relative = path.relative_to(root)
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as error:
                raise ResourceAccountingError(
                    f"inaccessible entry: {relative.as_posix()}: "
                    f"{type(error).__name__}"
                ) from error
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                symlink_count += 1
                try:
                    target = os.readlink(path)
                except OSError as error:
                    raise ResourceAccountingError(
                        f"inaccessible symbolic link: {relative.as_posix()}: "
                        f"{type(error).__name__}"
                    ) from error
                resolved_target = (
                    Path(target)
                    if Path(target).is_absolute()
                    else path.parent / target
                ).resolve(strict=False)
                try:
                    resolved_target.relative_to(root)
                except ValueError:
                    escaping_symlinks.append(relative.as_posix())
                continue
            if stat.S_ISDIR(mode):
                stack.append(path)
                continue
            if not stat.S_ISREG(mode):
                continue
            inode = (metadata.st_dev, metadata.st_ino)
            if inode in seen_inodes:
                hardlink_duplicates += 1
                continue
            seen_inodes.add(inode)
            category = resource_category(relative)
            apparent = int(metadata.st_size)
            allocated = int(metadata.st_blocks) * 512
            sparse = apparent > allocated
            value = ResourceFile(
                category=category,
                relative_path=_safe_label(relative, category),
                apparent_bytes=apparent,
                allocated_bytes=allocated,
                sparse=sparse,
            )
            category_total = categories[category]
            category_total.apparent_bytes += apparent
            category_total.allocated_bytes += allocated
            category_total.file_count += 1
            category_total.sparse_file_count += int(sparse)
            files[category].append(value)
            parents = list(relative.parents)
            for parent in parents:
                if str(parent) == ".":
                    label = "."
                else:
                    label = parent.as_posix()
                aggregate = directory_totals.setdefault(
                    (category, label), [0, 0, 0]
                )
                aggregate[0] += apparent
                aggregate[1] += allocated
                aggregate[2] += 1

    for category, total in categories.items():
        total.largest_files = sorted(
            files[category],
            key=lambda value: (-value.apparent_bytes, value.relative_path),
        )[:largest_n]
        directory_rows = [
            {
                "relative_path": path,
                "apparent_bytes": values[0],
                "allocated_bytes": values[1],
                "file_count": values[2],
            }
            for (row_category, path), values in directory_totals.items()
            if row_category == category
        ]
        total.largest_directories = sorted(
            directory_rows,
            key=lambda value: (
                -int(value["apparent_bytes"]),
                str(value["relative_path"]),
            ),
        )[:largest_n]

    elapsed = monotonic() - started
    return ResourceAccounting(
        sampled_at_monotonic=started + elapsed,
        elapsed_seconds=elapsed,
        entry_count=entry_count,
        hardlink_duplicates=hardlink_duplicates,
        symlink_count=symlink_count,
        escaping_symlinks=tuple(sorted(escaping_symlinks)),
        categories=categories,
        files=tuple(
            value
            for category in RESOURCE_CATEGORIES
            for value in files[category]
        ),
    )
