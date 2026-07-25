from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest

from sglab.resource_accounting import (
    PRESERVED_ARTIFACTS,
    RUNTIME_SCRATCH,
    account_execution_root,
)


class ResourceAccountingTests(unittest.TestCase):
    def test_sparse_file_reports_apparent_and_allocated_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "runtime-groups" / "g" / "director" / "scratch.bin"
            target.parent.mkdir(parents=True)
            target.touch()
            os.truncate(target, 8 * 1024 * 1024)
            report = account_execution_root(root)
            scratch = report.categories[RUNTIME_SCRATCH]
            self.assertEqual(scratch.apparent_bytes, 8 * 1024 * 1024)
            self.assertLess(scratch.allocated_bytes, scratch.apparent_bytes)
            self.assertEqual(scratch.sparse_file_count, 1)

    def test_hard_link_inode_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "arms" / "a" / "first.bin"
            first.parent.mkdir(parents=True)
            first.write_bytes(b"x" * 4096)
            second = first.with_name("second.bin")
            os.link(first, second)
            report = account_execution_root(root)
            preserved = report.categories[PRESERVED_ARTIFACTS]
            self.assertEqual(preserved.apparent_bytes, 4096)
            self.assertEqual(preserved.file_count, 1)
            self.assertEqual(report.hardlink_duplicates, 1)

    def test_symlink_escape_is_reported_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "execution"
            root.mkdir()
            outside = base / "outside.bin"
            outside.write_bytes(b"x" * 8192)
            (root / "escape").symlink_to(outside)
            report = account_execution_root(root)
            self.assertEqual(report.symlink_count, 1)
            self.assertEqual(report.escaping_symlinks, ("escape",))
            self.assertEqual(
                sum(
                    category.apparent_bytes
                    for category in report.categories.values()
                ),
                0,
            )

    def test_credential_contents_are_not_opened_or_reported_by_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            auth = root / "runtime-groups" / "g" / "director" / "codex-home"
            auth.mkdir(parents=True)
            target = auth / "auth.json"
            target.write_bytes(b"secret-never-read")
            target.chmod(0)
            try:
                report = account_execution_root(root)
            finally:
                target.chmod(0o600)
            credential = report.categories["credential_material"]
            self.assertEqual(credential.file_count, 1)
            self.assertEqual(
                credential.largest_files[0].relative_path,
                "credential_material/[redacted]",
            )

    def test_traversal_entry_bound_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in range(3):
                (root / f"{index}.bin").write_bytes(b"x")
            with self.assertRaisesRegex(RuntimeError, "entry limit"):
                account_execution_root(root, max_entries=2)

    def test_original_shape_separates_scratch_from_six_mib_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            preserved = root / "arms" / "a" / "response.bin"
            preserved.parent.mkdir(parents=True)
            preserved.write_bytes(b"x" * (6 * 1024 * 1024))
            scratch = (
                root
                / "runtime-groups"
                / "g"
                / "director"
                / "codex-sqlite-home"
                / "state.sqlite-wal"
            )
            scratch.parent.mkdir(parents=True)
            scratch.touch()
            os.truncate(scratch, 70 * 1024 * 1024)
            report = account_execution_root(root)
            self.assertEqual(
                report.categories[PRESERVED_ARTIFACTS].apparent_bytes,
                6 * 1024 * 1024,
            )
            self.assertEqual(
                report.categories[RUNTIME_SCRATCH].apparent_bytes,
                70 * 1024 * 1024,
            )
            self.assertGreater(
                sum(
                    category.apparent_bytes
                    for category in report.categories.values()
                ),
                64 * 1024 * 1024,
            )


if __name__ == "__main__":
    unittest.main()
