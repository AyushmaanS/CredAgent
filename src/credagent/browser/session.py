"""Browser session: CredAgent-owned headed Chrome (persistent profile) + Stagehand attached
through the masked model callback. Recorded in run state so a later process can re-attach."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credagent.browser.chrome import ChromeProcess
from credagent.state.models import BrowserSession


@dataclass
class Session:
    chrome: ChromeProcess
    browser: Any
    stagehand: Any | None
    page: Any

    def record(self) -> BrowserSession:
        return BrowserSession(
            chrome_pid=self.chrome.pid, cdp_port=self.chrome.port, profile_dir=str(self.chrome.profile_dir)
        )

    async def detach(self) -> None:
        """Leave Chrome running (e.g. a handoff is pending) — the profile and window stay."""
        try:
            await self.browser.disconnect()
        except Exception:  # noqa: BLE001, S110 - Chrome stays open either way; the run is already saved
            pass

    async def close(self) -> str:
        """Detach Stagehand, then quit Chrome gracefully so the profile is flushed (D-012)."""
        try:
            await self.browser.disconnect()
        finally:
            ended = await self.chrome.graceful_close()
        return ended


async def open_session(
    profile_dir: Path,
    *,
    headless: bool = False,
    model_callback: Any | None = None,
    existing: BrowserSession | None = None,
) -> Session:
    from stagehand import Stagehand, local_browser

    chrome = None
    if existing and existing.chrome_pid and existing.cdp_port:
        candidate = ChromeProcess(
            pid=existing.chrome_pid, port=existing.cdp_port, profile_dir=Path(existing.profile_dir)
        )
        if candidate.is_running():
            chrome = candidate
    if chrome is None:
        chrome = ChromeProcess.launch(profile_dir, headless=headless)
    browser = await local_browser.connect(cdp_url=chrome.cdp_url)
    # Stagehand must be attached for the page API. Offline, it gets a callback that refuses every
    # model call, and it is not offered to the loop for observe() (plain-code candidates only).
    sh = await Stagehand.create(browser=browser, model=model_callback or _refuse_model)
    page = await browser.context.active_page() or (await browser.context.pages())[0]
    return Session(chrome, browser, sh if model_callback is not None else None, page)


async def _refuse_model(params: Any) -> Any:
    raise RuntimeError("offline mode: no model calls allowed")
