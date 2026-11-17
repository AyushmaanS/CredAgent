"""Playwright over CDP to the CredAgent-owned Chrome (D-078).

`ChromeProcess` is unchanged: it launches Chrome with a persistent profile, survives this process, can be
re-attached from a later process on the saved CDP port, and is shut down gracefully so the profile is flushed.
Playwright only connects to it: `detach()` leaves Chrome running (a handoff is open), `close()` quits it.

Domain guard (second layer behind the code allow-list, D-043): main-frame navigations to hosts outside the
allowed domains are aborted at the browser. The person's handoffs lift it, as before.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from credagent.browser.chrome import ChromeProcess
from credagent.policy.hard_checks import host_allowed
from credagent.state.models import BrowserSession

_INTERNAL = ("chrome://", "chrome-extension://", "devtools://", "chrome-untrusted://")


@dataclass
class PwSession:
    chrome: ChromeProcess
    playwright: Any
    browser: Any
    context: Any
    page: Any
    reattached: bool = False
    _guard: Any = None

    def record(self) -> BrowserSession:
        return BrowserSession(chrome_pid=self.chrome.pid, cdp_port=self.chrome.port,
                              profile_dir=str(self.chrome.profile_dir))

    async def set_allowed_domains(self, domains: list[str] | None) -> None:
        """Abort main-frame navigations outside `domains`; None lifts the guard (person's handoff)."""
        if self._guard is not None:
            await self.context.unroute("**/*", self._guard)
            self._guard = None
        if not domains:
            return

        async def guard(route: Any) -> None:
            req = route.request
            if req.is_navigation_request() and req.frame.parent_frame is None:
                url = req.url
                if urlparse(url).scheme in ("http", "https") and not host_allowed(url, domains):
                    await route.abort("blockedbyclient")
                    return
            await route.continue_()

        self._guard = guard
        await self.context.route("**/*", guard)

    async def detach(self) -> None:
        """Disconnect and leave Chrome (and its window and profile) running."""
        try:
            await self.browser.close()  # for a CDP connection this only disconnects
        except Exception:  # noqa: BLE001, S110 - Chrome stays open either way; the run is already saved
            pass
        try:
            await self.playwright.stop()
        except Exception:  # noqa: BLE001, S110
            pass

    async def close(self) -> str:
        """Disconnect, then quit Chrome gracefully so the profile is flushed (D-012)."""
        await self.detach()
        return await self.chrome.graceful_close()


def pick_page(context: Any) -> Any | None:
    """The page the person is most likely looking at: the last real tab, not an internal one."""
    real = [p for p in context.pages if not p.url.startswith(_INTERNAL)]
    return real[-1] if real else None


async def _connect(pw: Any, chrome: ChromeProcess) -> tuple[Any, Any, Any]:
    browser = await pw.chromium.connect_over_cdp(chrome.cdp_url)
    context = browser.contexts[0] if browser.contexts else await browser.new_context()
    page = pick_page(context) or await context.new_page()
    return browser, context, page


async def open_pw_session(
    profile_dir: Path,
    *,
    headless: bool = False,
    existing: BrowserSession | None = None,
) -> PwSession:
    from playwright.async_api import async_playwright

    chrome = None
    reattached = False
    if existing and existing.chrome_pid and existing.cdp_port:
        candidate = ChromeProcess(pid=existing.chrome_pid, port=existing.cdp_port,
                                  profile_dir=Path(existing.profile_dir))
        if candidate.is_running():
            chrome, reattached = candidate, True
    if chrome is None:
        chrome = ChromeProcess.launch(profile_dir, headless=headless)
    pw = await async_playwright().start()
    try:
        try:
            browser, context, page = await _connect(pw, chrome)
        except Exception:
            if not reattached:
                raise
            # A Chrome that is running but cannot be driven: it has no window (the person closed it; on macOS Chrome
            # stays alive without one, and DevTools then refuses to be driven, D-094). Quit it, which releases the
            # profile, and open a fresh Chrome on the same profile: sign-ins live in the profile, so nothing is lost.
            await chrome.graceful_close()
            chrome = ChromeProcess.launch(profile_dir, headless=headless)
            reattached = False
            browser, context, page = await _connect(pw, chrome)
    except Exception:
        await pw.stop()
        raise
    return PwSession(chrome=chrome, playwright=pw, browser=browser, context=context, page=page,
                     reattached=reattached)
