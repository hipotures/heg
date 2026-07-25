from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Callable
import os
import shutil
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

EXPECTED_APP_SERVER_WRAPPERS = frozenset(
    {
        "apply_patch",
        "applypatch",
        "codex-execve-wrapper",
        "codex-linux-sandbox",
    }
)


class ResourceAccountingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TrustedSymlinkRoot:
    path: Path
    root_class: str


@dataclass(frozen=True, slots=True)
class SymlinkObservation:
    relative_path: str
    wrapper_basename: str
    classification: str
    target_trust_classification: str
    target_root_class: str | None
    policy_status: str
    policy_violation_code: str | None
    no_follow_confirmed: bool
    apparent_bytes: int
    allocated_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "wrapper_basename": self.wrapper_basename,
            "classification": self.classification,
            "target_trust_classification": self.target_trust_classification,
            "target_root_class": self.target_root_class,
            "policy_status": self.policy_status,
            "policy_violation_code": self.policy_violation_code,
            "no_follow_confirmed": self.no_follow_confirmed,
            "apparent_bytes": self.apparent_bytes,
            "allocated_bytes": self.allocated_bytes,
        }


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
    symlinks: tuple[SymlinkObservation, ...]
    accounting_status: str
    symlink_policy_status: str
    policy_violation_code: str | None
    categories: dict[str, CategoryAccounting]
    files: tuple[ResourceFile, ...]

    @property
    def escaping_symlinks(self) -> tuple[str, ...]:
        return tuple(
            value.relative_path
            for value in self.symlinks
            if value.classification == "unexpected_external"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "elapsed_seconds": self.elapsed_seconds,
            "entry_count": self.entry_count,
            "hardlink_duplicates": self.hardlink_duplicates,
            "symlink_count": self.symlink_count,
            "escaping_symlinks": list(self.escaping_symlinks),
            "symlinks": [value.as_dict() for value in self.symlinks],
            "accounting_status": self.accounting_status,
            "symlink_policy_status": self.symlink_policy_status,
            "policy_violation_code": self.policy_violation_code,
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


def discover_trusted_codex_roots(
    launcher: tuple[str, ...],
) -> tuple[TrustedSymlinkRoot, ...]:
    """Discover bounded installation roots from the server-owned launcher."""

    if not launcher:
        return ()
    raw = Path(launcher[0])
    located = raw if raw.is_absolute() else Path(shutil.which(str(raw)) or "")
    if not str(located):
        return ()
    try:
        executable = located.resolve(strict=True)
        metadata = executable.lstat()
    except OSError:
        return ()
    if not stat.S_ISREG(metadata.st_mode):
        return ()
    candidates = [
        TrustedSymlinkRoot(executable.parent, "launcher_directory"),
    ]
    if (
        executable.parent.name == "bin"
        and (
            executable.name == "codex.js"
            or raw.name == "codex"
        )
    ):
        candidates.insert(
            0,
            TrustedSymlinkRoot(
                executable.parent.parent,
                "codex_installation",
            ),
        )
    unique: dict[Path, TrustedSymlinkRoot] = {}
    for candidate in candidates:
        unique.setdefault(candidate.path, candidate)
    return tuple(unique.values())


def _expected_wrapper_location(relative: Path) -> bool:
    parts = relative.parts
    return (
        len(parts) == 8
        and parts[0] == "runtime-groups"
        and parts[2:6] == ("director", "codex-home", "tmp", "arg0")
        and parts[6].startswith("codex-arg0")
        and len(parts[6]) <= 80
    )


def _symlink_safe_label(relative: Path) -> str:
    if _expected_wrapper_location(relative):
        return f"app-server-tmp/arg0/{relative.name}"
    return f"runtime-scratch/{relative.name}"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _classify_symlink(
    path: Path,
    relative: Path,
    initial: os.stat_result,
    *,
    execution_root: Path,
    research_workspace: Path | None,
    trusted_roots: tuple[TrustedSymlinkRoot, ...],
    classification_hook: Callable[[Path], None] | None,
) -> SymlinkObservation:
    label = _symlink_safe_label(relative)
    basename = relative.name
    allocated = int(initial.st_blocks) * 512
    common = {
        "relative_path": label,
        "wrapper_basename": basename,
        "no_follow_confirmed": True,
        "apparent_bytes": int(initial.st_size),
        "allocated_bytes": allocated,
    }
    try:
        raw_target = os.readlink(path)
    except OSError:
        return SymlinkObservation(
            **common,
            classification="malformed_or_unreadable",
            target_trust_classification="unreadable",
            target_root_class=None,
            policy_status="rejected",
            policy_violation_code="unreadable_symlink",
        )
    target = Path(raw_target)
    target = target if target.is_absolute() else path.parent / target
    resolved_target = target.resolve(strict=False)
    internal = _is_within(resolved_target, execution_root)
    target_identity: tuple[int, int, int] | None = None
    try:
        target_metadata = os.lstat(resolved_target)
    except FileNotFoundError:
        classification = "broken"
        target_trust = "missing"
        root_class = None
        policy_code = "broken_symlink"
    except OSError:
        classification = "malformed_or_unreadable"
        target_trust = "unreadable"
        root_class = None
        policy_code = "unreadable_symlink"
    else:
        target_identity = (
            target_metadata.st_dev,
            target_metadata.st_ino,
            target_metadata.st_mode,
        )
        root_class = next(
            (
                trusted.root_class
                for trusted in trusted_roots
                if _is_within(resolved_target, trusted.path)
            ),
            None,
        )
        target_in_workspace = (
            research_workspace is not None
            and _is_within(resolved_target, research_workspace)
        )
        trusted_target = (
            root_class is not None
            and stat.S_ISREG(target_metadata.st_mode)
            and bool(target_metadata.st_mode & 0o111)
            and not bool(target_metadata.st_mode & stat.S_IWOTH)
            and not target_in_workspace
        )
        if (
            _expected_wrapper_location(relative)
            and basename in EXPECTED_APP_SERVER_WRAPPERS
            and trusted_target
        ):
            classification = "expected_runtime_wrapper"
            target_trust = "trusted_executable"
            policy_code = None
        elif internal:
            classification = "internal_nonfollowed"
            target_trust = "inside_execution_root"
            policy_code = "internal_symlink_not_permitted"
        else:
            classification = "unexpected_external"
            target_trust = (
                "untrusted_external"
                if root_class is None
                else "rejected_target_metadata"
            )
            policy_code = "unexpected_external_symlink"
    if classification_hook is not None:
        classification_hook(path)
    if target_identity is not None:
        try:
            stable_target = os.lstat(resolved_target)
        except OSError:
            stable_target = None
        if (
            stable_target is None
            or (
                stable_target.st_dev,
                stable_target.st_ino,
                stable_target.st_mode,
            )
            != target_identity
        ):
            return SymlinkObservation(
                **common,
                classification="malformed_or_unreadable",
                target_trust_classification="target_metadata_changed",
                target_root_class=None,
                policy_status="rejected",
                policy_violation_code="symlink_target_metadata_changed",
            )
    try:
        stable = os.lstat(path)
    except OSError:
        stable = None
    if (
        stable is None
        or stable.st_dev != initial.st_dev
        or stable.st_ino != initial.st_ino
        or stable.st_mode != initial.st_mode
    ):
        return SymlinkObservation(
            **common,
            classification="malformed_or_unreadable",
            target_trust_classification="metadata_changed",
            target_root_class=None,
            policy_status="rejected",
            policy_violation_code="symlink_metadata_changed",
        )
    return SymlinkObservation(
        **common,
        classification=classification,
        target_trust_classification=target_trust,
        target_root_class=root_class,
        policy_status="allowed" if policy_code is None else "rejected",
        policy_violation_code=policy_code,
    )


def account_execution_root(
    root: Path,
    *,
    research_workspace: Path | None = None,
    trusted_symlink_roots: tuple[TrustedSymlinkRoot, ...] = (),
    max_entries: int = 20_000,
    max_seconds: float = 2.0,
    largest_n: int = 8,
    symlink_classification_hook: Callable[[Path], None] | None = None,
) -> ResourceAccounting:
    """Account one private execution tree with lstat and no link traversal."""

    if max_entries < 1 or max_seconds <= 0 or largest_n < 1:
        raise ValueError("accounting bounds must be positive")
    started = monotonic()
    root = root.absolute()
    workspace = (
        research_workspace.resolve(strict=False)
        if research_workspace is not None
        else None
    )
    trusted_roots = tuple(
        TrustedSymlinkRoot(
            value.path.resolve(strict=False),
            value.root_class,
        )
        for value in trusted_symlink_roots
    )
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
    symlinks: list[SymlinkObservation] = []
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
                metadata = os.lstat(path)
            except OSError as error:
                raise ResourceAccountingError(
                    f"inaccessible entry: {relative.as_posix()}: "
                    f"{type(error).__name__}"
                ) from error
            mode = metadata.st_mode
            if stat.S_ISLNK(mode):
                symlink_count += 1
                symlinks.append(
                    _classify_symlink(
                        path,
                        relative,
                        metadata,
                        execution_root=root,
                        research_workspace=workspace,
                        trusted_roots=trusted_roots,
                        classification_hook=symlink_classification_hook,
                    )
                )
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
    rejected = [
        value for value in symlinks if value.policy_status == "rejected"
    ]
    accounting_status = (
        "error"
        if any(
            value.policy_violation_code
            in {
                "unreadable_symlink",
                "symlink_metadata_changed",
                "symlink_target_metadata_changed",
            }
            for value in rejected
        )
        else "ok"
    )
    return ResourceAccounting(
        sampled_at_monotonic=started + elapsed,
        elapsed_seconds=elapsed,
        entry_count=entry_count,
        hardlink_duplicates=hardlink_duplicates,
        symlink_count=symlink_count,
        symlinks=tuple(
            sorted(symlinks, key=lambda value: value.relative_path)
        ),
        accounting_status=accounting_status,
        symlink_policy_status="failed" if rejected else "passed",
        policy_violation_code=(
            rejected[0].policy_violation_code if rejected else None
        ),
        categories=categories,
        files=tuple(
            value
            for category in RESOURCE_CATEGORIES
            for value in files[category]
        ),
    )
