from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ContractRun:
    output_json: Path
    screenshot: Path
    stderr_log: Path
    stdout_log: Path
    ui: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Selenium UI contracts for both JupyterLab and Notebook 7.",
    )
    parser.add_argument("--jupyter-exe", required=True)
    parser.add_argument("--root-dir", required=True)
    parser.add_argument("--notebook", required=True)
    parser.add_argument("--token", default="test-token")
    parser.add_argument("--base-port", type=int, default=8898)
    parser.add_argument("--check-connect", action="store_true")
    parser.add_argument("--check-config-init", action="store_true")
    parser.add_argument(
        "--output-json",
        default="tmp-selenium-contract-suite.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs = (
        ContractRun(
            ui="lab",
            output_json=Path("tmp-selenium-smoke-lab.json"),
            screenshot=Path("tmp-selenium-smoke-lab.png"),
            stdout_log=Path("tmp-selenium-jupyter-lab.out.log"),
            stderr_log=Path("tmp-selenium-jupyter-lab.err.log"),
        ),
        ContractRun(
            ui="notebook",
            output_json=Path("tmp-selenium-smoke-notebook.json"),
            screenshot=Path("tmp-selenium-smoke-notebook.png"),
            stdout_log=Path("tmp-selenium-jupyter-notebook.out.log"),
            stderr_log=Path("tmp-selenium-jupyter-notebook.err.log"),
        ),
    )

    suite_payload: dict[str, object] = {"runs": []}
    failures: list[str] = []
    for index, run in enumerate(runs):
        exit_code = run_smoke(
            args=args,
            run=run,
            port=args.base_port + index,
        )
        payload = json.loads(run.output_json.read_text(encoding="utf-8"))
        payload["ui"] = run.ui
        payload["exitCode"] = exit_code
        suite_payload["runs"].append(payload)
        if exit_code != 0:
            failures.append(run.ui)

    suite_payload["failedModes"] = failures
    suite_payload["ok"] = failures == []
    output_path = Path(args.output_json)
    output_path.write_text(json.dumps(suite_payload, indent=2), encoding="utf-8")
    print(json.dumps(suite_payload, indent=2))
    return 0 if failures == [] else 1


def run_smoke(
    *,
    args: argparse.Namespace,
    run: ContractRun,
    port: int,
) -> int:
    command = [
        sys.executable,
        "scripts/selenium_smoke.py",
        "--jupyter-exe",
        args.jupyter_exe,
        "--root-dir",
        args.root_dir,
        "--notebook",
        args.notebook,
        "--ui",
        run.ui,
        "--port",
        str(port),
        "--token",
        args.token,
        "--output-json",
        str(run.output_json),
        "--screenshot",
        str(run.screenshot),
        "--log-prefix",
        run.stdout_log.with_suffix("").name,
    ]
    if args.check_connect:
        command.append("--check-connect")
    if args.check_config_init:
        command.append("--check-config-init")

    completed = subprocess.run(
        command,
        check=False,
        cwd=Path.cwd(),
        text=True,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
