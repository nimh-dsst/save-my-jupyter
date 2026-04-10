from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
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
from selenium.webdriver.common.keys import Keys
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
    connect_error_message: str | None
    connect_error_scoped_to_labarchives: bool
    tags_input_accepts_commas: bool
    tags_input_value_after_typing: str | None
    config_path_hint: str | None
    config_status_message: str | None
    config_status_scoped_to_project_config: bool
    config_file_exists_after_click: bool


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
    parser.add_argument("--check-connect", action="store_true")
    parser.add_argument("--check-config-init", action="store_true")
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


def start_jupyter(
    args: argparse.Namespace,
) -> tuple[subprocess.Popen[str], Path, Path, Path]:
    log_prefix = Path(args.log_prefix)
    stdout_path = log_prefix.with_suffix(".out.log")
    stderr_path = log_prefix.with_suffix(".err.log")
    stdout_handle = stdout_path.open("w", encoding="utf-8")
    stderr_handle = stderr_path.open("w", encoding="utf-8")
    workspaces_dir = Path(
        tempfile.mkdtemp(prefix="jupyter-workspaces-", dir=Path.cwd())
    )
    process = subprocess.Popen(
        [
            args.jupyter_exe,
            "--no-browser",
            f"--ServerApp.root_dir={args.root_dir}",
            f"--IdentityProvider.token={args.token}",
            "--ServerApp.password=",
            f"--ServerApp.port={args.port}",
            "--ServerApp.port_retries=0",
            f"--LabApp.workspaces_dir={workspaces_dir}",
        ],
        cwd=args.root_dir,
        stdout=stdout_handle,
        stderr=stderr_handle,
        text=True,
    )
    return process, stdout_path, stderr_path, workspaces_dir


def build_driver() -> tuple[WebDriver, Path]:
    cache_path = Path.cwd() / ".selenium-cache"
    os.environ.setdefault("SE_CACHE_PATH", str(cache_path))
    profile_dir = Path(
        tempfile.mkdtemp(prefix="selenium-profile-", dir=Path.cwd())
    )

    options = ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1600,1200")
    options.add_argument(f"--user-data-dir={profile_dir}")
    return webdriver.Chrome(options=options), profile_dir


def find_toolbar_button(driver: WebDriver, selector: str) -> Any | None:
    script = """
    const selector = arguments[0];
    return document.querySelector(selector);
    """
    return driver.execute_script(script, selector)


def find_visible_notebook_panel(driver: WebDriver) -> Any | None:
    script = """
    return Array.from(document.querySelectorAll('.jp-NotebookPanel')).find(
      (panel) => {
        const rect = panel.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }
    ) ?? null;
    """
    return driver.execute_script(script)


def find_visible_snapshot_panel(driver: WebDriver) -> Any | None:
    script = """
    return Array.from(document.querySelectorAll('.smj-SnapshotPanel')).find(
      (panel) => {
        const rect = panel.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }
    ) ?? null;
    """
    return driver.execute_script(script)


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

    notebook_panel = wait.until(find_visible_notebook_panel)

    toolbar_buttons = driver.execute_script(
        """
        const notebookPanel = arguments[0];
        return Array.from(
          notebookPanel.querySelectorAll(
            '.jp-Toolbar button, .jp-Toolbar .jp-ToolbarButtonComponent'
          )
        )
          .map((button) => ({
            className: button.className,
            text: (button.textContent || '').trim(),
            title: button.getAttribute('title') || ''
          }));
        """,
        notebook_panel,
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
        lambda browser: browser.execute_script(
            """
            const notebookPanel = arguments[0];
            return notebookPanel?.querySelector(
              '.smj-ToolbarButton:not(.smj-ToolbarButton--trigger)'
            ) ?? null;
            """,
            notebook_panel,
        )
    )
    driver.execute_script("arguments[0].click();", save_button)

    try:
        panel = wait.until(find_visible_snapshot_panel)
    except TimeoutException as error:
        raise RuntimeError(
            "Save My Jupyter panel did not appear after clicking the toolbar button.",
        ) from error

    panel_header = driver.execute_script(
        """
        const panel = arguments[0];
        const header = panel?.querySelector('.smj-SnapshotPanel__headerTitle');
        return header ? header.textContent.trim() : null;
        """,
        panel,
    )
    panel_contains_trigger_controls = bool(
        driver.execute_script(
            """
            const panel = arguments[0];
            if (!panel) {
              return false;
            }
            return panel.textContent.includes('Trigger cells') &&
              panel.textContent.includes('Selected cell') &&
              panel.textContent.includes('Mark selected cell');
            """,
            panel,
        )
    )
    right_sidebar_visible = bool(
        driver.execute_script(
            """
            const panel = arguments[0];
            if (!panel) {
              return false;
            }
            const shell = panel.closest(
              '.jp-SideBar, .jp-right-stack, .jp-LabShell, .jp-SplitPanel'
            );
            const rect = panel.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && shell !== null;
            """,
            panel,
        )
    )
    selected_cell_label = driver.execute_script(
        """
        const panel = arguments[0];
        const values = Array.from(
          panel?.querySelectorAll('.smj-SnapshotPanel__facts dd') || []
        )
          .map((node) => node.textContent.trim());
        return values[0] ?? null;
        """,
        panel,
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
    connect_error_message: str | None = None
    connect_error_scoped_to_labarchives = False
    tags_input = wait.until(
        lambda browser: browser.execute_script(
            """
            const panel = arguments[0];
            return Array.from(
              panel?.querySelectorAll('label.smj-SnapshotPanel__field') || []
            ).find((label) =>
              label.querySelector('span')?.textContent?.trim() === 'Tags'
            )?.querySelector('input') ?? null;
            """,
            panel,
        )
    )
    tags_input.send_keys(Keys.CONTROL, "a", Keys.BACKSPACE)
    tags_input.send_keys("baseline, follow-up,")
    tags_input_value_after_typing = tags_input.get_attribute("value")
    tags_input_accepts_commas = tags_input_value_after_typing == "baseline, follow-up,"

    config_path_hint: str | None = None
    if args.check_connect:
        labarchives_section = driver.execute_script(
            """
            const panel = arguments[0];
            return Array.from(
              panel?.querySelectorAll('.smj-SnapshotPanel__section') || []
            )
              .find((section) => section.textContent.includes('LabArchives'));
            """,
            panel,
        )
        connect_button = wait.until(
            lambda browser: browser.execute_script(
                """
                const section = arguments[0];
                return section?.querySelector('button');
                """,
                labarchives_section,
            )
        )
        driver.execute_script("arguments[0].click();", connect_button)
        status_message = wait.until(
            lambda browser: browser.execute_script(
                """
                const section = arguments[0];
                const status = section?.querySelector('.smj-SnapshotPanel__status');
                if (!status) {
                  return null;
                }
                const text = (status.textContent || '').trim();
                return text === '' ? null : text;
                """,
                labarchives_section,
            )
        )
        connect_error_message = str(status_message)
        connect_error_scoped_to_labarchives = True

    config_status_message: str | None = None
    config_status_scoped_to_project_config = False
    config_file_exists_after_click = False
    if args.check_config_init:
        config_section = driver.execute_script(
            """
            const panel = arguments[0];
            return Array.from(
              panel?.querySelectorAll('.smj-SnapshotPanel__section') || []
            )
              .find((section) => section.textContent.includes('Project config'));
            """,
            panel,
        )
        config_button = wait.until(
            lambda browser: browser.execute_script(
                """
                const section = arguments[0];
                return Array.from(section?.querySelectorAll('button') || [])
                  .find((button) => button.textContent.includes('config'));
                """,
                config_section,
            )
        )
        driver.execute_script("arguments[0].click();", config_button)
        status_message = wait.until(
            lambda browser: browser.execute_script(
                """
                const section = arguments[0];
                const status = section?.querySelector('.smj-SnapshotPanel__status');
                if (!status) {
                  return null;
                }
                const text = (status.textContent || '').trim();
                return text === '' ? null : text;
                """,
                config_section,
            )
        )
        config_status_message = str(status_message)
        config_status_scoped_to_project_config = True
        config_path = driver.execute_script(
            """
            const section = arguments[0];
            const hints = Array.from(
              section?.querySelectorAll('.smj-SnapshotPanel__hint') || []
            );
            return hints.length > 0 ? (hints[0].textContent || '').trim() : null;
            """,
            config_section,
        )
        if isinstance(config_path, str) and config_path != "":
            config_path_hint = config_path
            config_file_exists_after_click = Path(config_path).exists()
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
        connect_error_message=connect_error_message,
        connect_error_scoped_to_labarchives=connect_error_scoped_to_labarchives,
        tags_input_accepts_commas=tags_input_accepts_commas,
        tags_input_value_after_typing=tags_input_value_after_typing,
        config_path_hint=config_path_hint,
        config_status_message=config_status_message,
        config_status_scoped_to_project_config=config_status_scoped_to_project_config,
        config_file_exists_after_click=config_file_exists_after_click,
    )


def main() -> int:
    args = parse_args()
    process, stdout_path, stderr_path, workspaces_dir = start_jupyter(args)
    driver: WebDriver | None = None
    profile_dir: Path | None = None
    try:
        ready_url = (
            f"http://127.0.0.1:{args.port}/lab?token={args.token}"
            if args.ui == "lab"
            else f"http://127.0.0.1:{args.port}/tree?token={args.token}"
        )
        wait_for_http_ready(ready_url)
        driver, profile_dir = build_driver()
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
        if profile_dir is not None:
            subprocess.run(
                ["cmd", "/c", "rmdir", "/s", "/q", str(profile_dir)],
                check=False,
            )
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        subprocess.run(
            ["cmd", "/c", "rmdir", "/s", "/q", str(workspaces_dir)],
            check=False,
        )
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
