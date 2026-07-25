#!/usr/bin/env python3
from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import asyncio
import json

from sglab.research.app_server_client import AppServerClient, AppServerConfig
from sglab.resource_accounting import (
    EXPECTED_APP_SERVER_WRAPPERS,
    account_execution_root,
    discover_trusted_codex_roots,
)


async def smoke(runtime_root: Path) -> dict[str, object]:
    root = runtime_root.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    application_data = root / "runtime-groups" / "installed-smoke"
    config = AppServerConfig(
        application_data=application_data,
        launcher=("codex",),
        request_timeout_seconds=10,
        environment_exclusions=(
            "SGLAB_CODEX_AUTH_SOURCE",
            "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON",
        ),
    )
    client = AppServerClient(config)
    process_id: int | None = None
    process = None
    try:
        await client.start()
        assert client.process is not None
        process = client.process
        process_id = client.process.pid
        accounting = account_execution_root(
            root,
            research_workspace=Path.cwd().resolve(),
            trusted_symlink_roots=discover_trusted_codex_roots(
                config.launcher
            ),
        )
        wrappers = [
            value
            for value in accounting.symlinks
            if value.classification == "expected_runtime_wrapper"
        ]
        observed = {value.wrapper_basename for value in wrappers}
        compatible = (
            observed == EXPECTED_APP_SERVER_WRAPPERS
            and accounting.accounting_status == "ok"
            and accounting.symlink_policy_status == "passed"
        )
        observations = [
            value.as_dict() for value in accounting.symlinks
        ]
    finally:
        await client.close()
    assert process is not None
    return {
        "ok": compatible,
        "thread_started": False,
        "turn_started": False,
        "model_inference_starts": 0,
        "auth_access": False,
        "wrapper_names": sorted(observed),
        "wrapper_classifications": sorted(
            {
                value.classification
                for value in wrappers
            }
        ),
        "symlink_count": len(observations),
        "symlink_observations": observations,
        "target_root_classes": sorted(
            {
                str(value.target_root_class)
                for value in wrappers
            }
        ),
        "symlink_targets_followed": False,
        "process_id_recorded": process_id is not None,
        "process_reaped": process.returncode is not None,
        "return_code": process.returncode,
    }


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--runtime-root", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(smoke(args.runtime_root))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
