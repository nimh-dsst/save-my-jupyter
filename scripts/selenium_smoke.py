from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver import ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait

if TYPE_CHECKING:
    from selenium.webdriver.chrome.webdriver import WebDriver


@dataclass(slots=True)
class SmokeResult:
    ui_mode: str
    page_title: str
    current_url: str
    toolbar_entries: list[dict[str, str]]
    save_button_found: bool
    trigger_button_found: bool
    right_sidebar_visible: bool
    panel_visible_after_click: bool
    panel_header: str | None
    panel_contains_trigger_controls: bool
    selected_cell_label: str | None
    trigger_button_label: str | None
    trigger_left_highlight_present: bool
    trigger_pill_visible_after_click: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Selenium smoke test against JupyterLab.",
    )
    parser.add_argument("--jupyter-exe", required=True)
    parser.add_argument("--root-dir", required=True)
    parser.add_argument("--notebook", required=True)
    parser.add_argument("--ui", choices=("lab", "notebook"), default="lab")
    parser.add_argument("--port", type=int, default=8898)
    parser.add_argument("--token", default="test-token")
    parser.add_argument("--log-prefix", default="tmp-selenium-jupyter")
    parser.add_argument("--output-json", default="tmp-selenium-smoke.json")
    parser.add_argument("--screenshot", default="tmp-selenium-smoke.png")
    return parser.parse_args()


def wait_for_http_ready(base_url: str, timeout_seconds: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(base_url, timeout=5) as response:
                if response.status == 200:
                    return
        except (TimeoutError, URLError) as error:
            last_error = error
            time.sleep(1)
    raise RuntimeError(
        f"Jupyter server at {base_url} did not become ready.",
    ) from last_error


def start_jupyter(args: argparse.Namespace) -> tuple[subprocess.Popen[str], Path, Path]:
    log_prefix = Path(args.log_prefix)
    stdout_path = log_prefix.with_suffix(".out.log")
    stderr_path = log_prefix.with_suffix(".err.log")
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            args.jupyter_exe,
            "--no-browser",
            f"--ServerApp.root_dir={args.root_dir}",
            f"--IdentityProvider.token={args.token}",
            "--ServerApp.password=",
            f"--ServerApp.port={args.port}",
            "--ServerApp.port_retries=0",
        ],
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    return process, stdout_path, stderr_path


def build_driver() -> WebDriver:
    cache_path = Path.cwd() / ".selenium-cache"
    os.environ.setdefault("SE_CACHE_PATH", str(cache_path))

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,1200")
    options.add_argument(f"--user-data-dir={Path.cwd() / '.selenium-profile'}")
    return webdriver.Chrome(options=options)


def find_toolbar_button(driver: WebDriver, selector: str) -> Any | None:
    script = """
    const selector = arguments[0];
    return document.querySelector(selector);
    """
    return driver.execute_script(script, selector)


def run_smoke(driver: WebDriver, args: argparse.Namespace) -> SmokeResult:
    notebook_url = (
        f"http://127.0.0.1:{args.port}/lab/tree/{quote(args.notebook)}?token={args.token}"
        if args.ui == "lab"
        else f"http://127.0.0.1:{args.port}/notebooks/{quote(args.notebook)}?token={args.token}"
    )
    driver.get(notebook_url)

    wait = WebDriverWait(driver, 60)
    wait.until(
        expected_conditions.presence_of_element_located(
            (By.CSS_SELECTOR, ".jp-NotebookPanel"),
        )
    )
    wait.until(
        expected_conditions.presence_of_element_located(
            (By.CSS_SELECTOR, ".jp-Toolbar"),
        )
    )

    toolbar_buttons = driver.execute_script(
        """
        return Array.from(
          document.querySelectorAll(
            '.jp-Toolbar button, .jp-Toolbar .jp-ToolbarButtonComponent'
          )
        )
          .map((button) => ({
            className: button.className,
            text: (button.textContent || '').trim(),
            title: button.getAttribute('title') || ''
          }));
        """
    )
    save_button_found = any(
        "smj-ToolbarButton" in (button["className"] or "")
        and (
            "Save" in (button["text"] or "")
            or "Save My Jupyter" in (button["title"] or "")
        )
        for button in toolbar_buttons
    )
    trigger_button_found = any(
        "smj-ToolbarButton--trigger" in (button["className"] or "")
        and (
            "Trigger" in (button["text"] or "")
            or "trigger" in (button["title"] or "").lower()
        )
        for button in toolbar_buttons
    )

    save_button = wait.until(
        lambda browser: find_toolbar_button(
            browser,
            ".smj-ToolbarButton:not(.smj-ToolbarButton--trigger)",
        )
    )
    driver.execute_script("arguments[0].click();", save_button)

    try:
        wait.until(
            expected_conditions.presence_of_element_located(
                (By.CSS_SELECTOR, ".smj-SnapshotPanel"),
            )
        )
    except TimeoutException as error:
        raise RuntimeError(
            "Save My Jupyter panel did not appear after clicking the toolbar button.",
        ) from error

    panel_header = driver.execute_script(
        """
        const panel = document.querySelector('.smj-SnapshotPanel');
        const header = panel?.querySelector('.smj-SnapshotPanel__headerTitle');
        return header ? header.textContent.trim() : null;
        """
    )
    panel_contains_trigger_controls = bool(
        driver.execute_script(
            """
            const panel = document.querySelector('.smj-SnapshotPanel');
            if (!panel) {
              return false;
            }
            return panel.textContent.includes('Trigger cells') &&
              panel.textContent.includes('Selected cell') &&
              panel.textContent.includes('Mark selected cell');
            """
        )
    )
    right_sidebar_visible = bool(
        driver.execute_script(
            """
            const panel = document.querySelector('.smj-SnapshotPanel');
            if (!panel) {
              return false;
            }
            const shell = panel.closest(
              '.jp-SideBar, .jp-right-stack, .jp-LabShell, .jp-SplitPanel'
            );
            const rect = panel.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && shell !== null;
            """
        )
    )
    selected_cell_label = driver.execute_script(
        """
        const values = Array.from(
          document.querySelectorAll('.smj-SnapshotPanel__facts dd')
        )
          .map((node) => node.textContent.trim());
        return values[0] ?? null;
        """
    )
    trigger_toggle = wait.until(
        expected_conditions.presence_of_element_located(
            (
                By.XPATH,
                "//button[contains(normalize-space(.), 'Mark selected cell') or "
                "contains(normalize-space(.), 'Unmark selected cell')]",
            )
        )
    )
    trigger_button_label = trigger_toggle.text.strip() or None
    driver.execute_script("arguments[0].click();", trigger_toggle)

    wait.until(
        lambda browser: bool(
            browser.execute_script(
                "return document.querySelector("
                "'.jp-Notebook .jp-Cell.smj-Cell--trigger'"
                ") !== null;",
            )
        )
    )

    trigger_decoration = driver.execute_script(
        """
        const cell = document.querySelector('.jp-Notebook .jp-Cell.smj-Cell--trigger');
        if (!cell) {
          return { hasLeftHighlight: false, pillVisible: false };
        }
        const cellStyle = window.getComputedStyle(cell);
        const afterStyle = window.getComputedStyle(cell, '::after');
        const content = afterStyle.content || '';
        return {
          hasLeftHighlight: cellStyle.boxShadow !== 'none',
          pillVisible: content !== 'none' && content !== 'normal' && content !== '""'
        };
        """
    )
    driver.save_screenshot(args.screenshot)

    return SmokeResult(
        ui_mode=args.ui,
        page_title=driver.title,
        current_url=driver.current_url,
        toolbar_entries=toolbar_buttons,
        save_button_found=save_button_found,
        trigger_button_found=trigger_button_found,
        right_sidebar_visible=right_sidebar_visible,
        panel_visible_after_click=True,
        panel_header=panel_header,
        panel_contains_trigger_controls=panel_contains_trigger_controls,
        selected_cell_label=selected_cell_label,
        trigger_button_label=trigger_button_label,
        trigger_left_highlight_present=bool(trigger_decoration["hasLeftHighlight"]),
        trigger_pill_visible_after_click=bool(trigger_decoration["pillVisible"]),
    )


def main() -> int:
    args = parse_args()
    process, stdout_path, stderr_path = start_jupyter(args)
    driver: WebDriver | None = None
    try:
        ready_url = (
            f"http://127.0.0.1:{args.port}/lab?token={args.token}"
            if args.ui == "lab"
            else f"http://127.0.0.1:{args.port}/tree?token={args.token}"
        )
        wait_for_http_ready(ready_url)
        driver = build_driver()
        result = run_smoke(driver, args)
        output_path = Path(args.output_json)
        output_path.write_text(
            json.dumps(asdict(result), indent=2),
            encoding="utf-8",
        )
        print(json.dumps(asdict(result), indent=2))
        return 0
    finally:
        if driver is not None:
            driver.quit()
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        if process.returncode not in (0, None):
            print(
                (
                    "Jupyter exited with code "
                    f"{process.returncode}. See {stdout_path} and {stderr_path}."
                ),
                file=sys.stderr,
            )


if __name__ == "__main__":
    raise SystemExit(main())
