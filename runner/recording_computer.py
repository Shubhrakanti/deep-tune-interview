"""PlaywrightComputer subclass that captures everything the M2 review UI needs.

Wraps the vendored `PlaywrightComputer` with three additions, none of which
touch the vendor code:

  - Records a .webm video of the session (Playwright's built-in context
    recording).
  - Saves a PNG screenshot of every observation to `screenshots/step_NNNN.png`.
  - Appends a JSONL event log to `trajectory.jsonl` with one row per action
    and one row per observation, in causal order.

The `append_event` method is also exposed publicly so the runner can inject
non-Computer events (task_start, final_answer, grade) into the same stream.

About the `_depth` guard: upstream `type_text_at` internally calls
`self.key_combination(...)` (which itself calls `current_state()`); a naive
wrapper would log multiple nested actions + observations for one logical agent
action. The depth counter ensures we only log the outermost call.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Literal

import termcolor
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR = REPO_ROOT / "vendor" / "computer-use-preview"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

from computers import EnvState  # noqa: E402
from computers.playwright.playwright import PlaywrightComputer  # noqa: E402


def _now_iso() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class RecordingComputer(PlaywrightComputer):
    """Drop-in replacement for `PlaywrightComputer` that captures artifacts."""

    def __init__(
        self,
        run_dir: Path,
        screen_size: tuple[int, int],
        initial_url: str = "https://www.google.com",
        search_engine_url: str = "https://www.google.com",
        highlight_mouse: bool = False,
    ):
        super().__init__(
            screen_size=screen_size,
            initial_url=initial_url,
            search_engine_url=search_engine_url,
            highlight_mouse=highlight_mouse,
        )
        self._run_dir = Path(run_dir)
        self._video_dir = self._run_dir / "_video_tmp"
        self._shots_dir = self._run_dir / "screenshots"
        self._trajectory_path = self._run_dir / "trajectory.jsonl"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._video_dir.mkdir(parents=True, exist_ok=True)
        self._shots_dir.mkdir(parents=True, exist_ok=True)
        self._trajectory_path.touch(exist_ok=True)
        self._seq = 0
        self._step = 0
        self._depth = 0
        self._lock = Lock()

    # ----- public properties ----------------------------------------------

    @property
    def step_count(self) -> int:
        """Number of observations recorded so far."""
        return self._step

    # ----- event log -------------------------------------------------------

    def append_event(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._seq += 1
            event = {
                "ts": _now_iso(),
                "seq": self._seq,
                "kind": kind,
                "data": data,
            }
            with self._trajectory_path.open("a") as f:
                f.write(json.dumps(event, default=str) + "\n")

    def _record_observation(self, state: EnvState) -> None:
        try:
            self._step += 1
            shot_rel = f"screenshots/step_{self._step:04d}.png"
            (self._run_dir / shot_rel).write_bytes(state.screenshot)
            # Page title is much more readable than the raw URL for the UI
            # ("Sign in · Metabase" vs ".../auth/login?redirect=%2F"). Best
            # effort — never let a title read failure break the recording.
            title = ""
            try:
                title = self._page.title() or ""
            except Exception:
                pass
            self.append_event(
                "observation",
                {
                    "screenshot": shot_rel,
                    "url": state.url,
                    "title": title,
                    "step": self._step,
                },
            )
        except Exception as e:
            print(f"[recording] failed to record observation: {e}")

    def _do(
        self,
        name: str,
        args: dict[str, Any],
        super_method: Callable[..., EnvState],
        *call_args: Any,
    ) -> EnvState:
        is_outer = self._depth == 0
        if is_outer:
            self.append_event("action", {"name": name, "args": args})
        self._depth += 1
        try:
            result = super_method(self, *call_args)
        finally:
            self._depth -= 1
        if is_outer and isinstance(result, EnvState):
            self._record_observation(result)
        return result

    # ----- lifecycle -------------------------------------------------------

    def __enter__(self):
        # Mirrors upstream PlaywrightComputer.__enter__ (kept in sync with
        # vendor/computer-use-preview/computers/playwright/playwright.py) but
        # adds `record_video_dir` + `record_video_size` so each session writes
        # a .webm we can replay in the review UI.
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            args=[
                "--disable-extensions",
                "--disable-file-system",
                "--disable-plugins",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-sync",
            ],
            headless=bool(os.environ.get("PLAYWRIGHT_HEADLESS", False)),
        )
        self._context = self._browser.new_context(
            viewport={
                "width": self._screen_size[0],
                "height": self._screen_size[1],
            },
            record_video_dir=str(self._video_dir),
            record_video_size={
                "width": self._screen_size[0],
                "height": self._screen_size[1],
            },
        )
        self._page = self._context.new_page()
        self._page.goto(self._initial_url)
        self._context.on("page", self._handle_new_page)
        termcolor.cprint(
            "Started local playwright (recording).",
            color="green",
            attrs=["bold"],
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        ret = super().__exit__(exc_type, exc_val, exc_tb)
        # Playwright writes the webm with a random hash on context.close(),
        # which super().__exit__ just triggered. Rename to a stable path.
        try:
            webms = sorted(self._video_dir.glob("*.webm"))
            if webms:
                webms[-1].replace(self._run_dir / "video.webm")
                for w in self._video_dir.glob("*.webm"):
                    w.unlink(missing_ok=True)
            self._video_dir.rmdir()
        except Exception as e:
            print(f"[recording] failed to finalize video: {e}")
        return ret

    # ----- action wrappers (one line each via _do) -------------------------

    def open_web_browser(self) -> EnvState:
        return self._do("open_web_browser", {}, PlaywrightComputer.open_web_browser)

    def click_at(self, x: int, y: int) -> EnvState:
        return self._do("click_at", {"x": x, "y": y}, PlaywrightComputer.click_at, x, y)

    def hover_at(self, x: int, y: int) -> EnvState:
        return self._do("hover_at", {"x": x, "y": y}, PlaywrightComputer.hover_at, x, y)

    def type_text_at(
        self,
        x: int,
        y: int,
        text: str,
        press_enter: bool = False,
        clear_before_typing: bool = True,
    ) -> EnvState:
        return self._do(
            "type_text_at",
            {
                "x": x,
                "y": y,
                "text": text,
                "press_enter": press_enter,
                "clear_before_typing": clear_before_typing,
            },
            PlaywrightComputer.type_text_at,
            x,
            y,
            text,
            press_enter,
            clear_before_typing,
        )

    def scroll_document(
        self, direction: Literal["up", "down", "left", "right"]
    ) -> EnvState:
        return self._do(
            "scroll_document",
            {"direction": direction},
            PlaywrightComputer.scroll_document,
            direction,
        )

    def scroll_at(
        self,
        x: int,
        y: int,
        direction: Literal["up", "down", "left", "right"],
        magnitude: int = 800,
    ) -> EnvState:
        return self._do(
            "scroll_at",
            {"x": x, "y": y, "direction": direction, "magnitude": magnitude},
            PlaywrightComputer.scroll_at,
            x,
            y,
            direction,
            magnitude,
        )

    def wait_5_seconds(self) -> EnvState:
        return self._do("wait_5_seconds", {}, PlaywrightComputer.wait_5_seconds)

    def go_back(self) -> EnvState:
        return self._do("go_back", {}, PlaywrightComputer.go_back)

    def go_forward(self) -> EnvState:
        return self._do("go_forward", {}, PlaywrightComputer.go_forward)

    def search(self) -> EnvState:
        return self._do("search", {}, PlaywrightComputer.search)

    def navigate(self, url: str) -> EnvState:
        return self._do("navigate", {"url": url}, PlaywrightComputer.navigate, url)

    def key_combination(self, keys: list[str]) -> EnvState:
        return self._do(
            "key_combination",
            {"keys": list(keys)},
            PlaywrightComputer.key_combination,
            keys,
        )

    def drag_and_drop(
        self, x: int, y: int, destination_x: int, destination_y: int
    ) -> EnvState:
        return self._do(
            "drag_and_drop",
            {
                "x": x,
                "y": y,
                "destination_x": destination_x,
                "destination_y": destination_y,
            },
            PlaywrightComputer.drag_and_drop,
            x,
            y,
            destination_x,
            destination_y,
        )
