"""Playwright executor (D-078): click · type · select · navigate · scroll · inspect · back · wait.

The executor does exactly what it is told and reports what happened. It decides nothing:
  * what to do is chosen by the LLM; whether it is allowed is decided by code (policy) *before* a call here;
  * a ref is valid only for the snapshot that issued it, and only while the page is still at that URL;
  * it never types into password or read-only fields, never opens non-http(s) addresses, and never returns a
    field's value: `inspect` on a field answers only whether it holds one of the run's approved values;
  * every string it returns is masked.

Failures come back as `ExecResult(ok=False, error=…)` so the model can see them; a closed browser raises
`BrowserClosed` so the run can end with a plain message.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from credagent.browser.snapshot import Element, Snapshot
from credagent.secrets.masking import Masker

INSPECT_CHARS = 600

_MATCH_JS = """
(el, approved) => {
  const v = typeof el.value === 'string' ? el.value.trim() : '';
  return Object.keys(approved).filter(k => approved[k] === v);
}
"""


class BrowserClosed(Exception):
    """The browser window or Chrome went away under the run."""


@dataclass
class ExecResult:
    ok: bool
    action: str
    detail: str = ""  # short, masked, never a field value
    error: str | None = None
    url: str = ""  # masked address after the action
    new_tab: bool = False
    text: str | None = None  # inspect output (masked)

    def summary(self) -> str:
        return (self.detail if self.ok else f"failed: {self.error}")[:300]


class Executor:
    def __init__(self, page: Any, masker: Masker, *, approved: dict[str, str] | None = None,
                 settle_ms: int = 700, timeout_ms: int = 8000) -> None:
        self.page = page
        self.masker = masker
        self.approved = dict(approved or {})  # approved non-secret values, by key (app_name, redirect_uri …)
        self.settle_ms = settle_ms
        self.timeout_ms = timeout_ms

    # ------------------------------------------------------------ helpers
    def _res(self, ok: bool, action: str, detail: str = "", error: str | None = None, **kw: Any) -> ExecResult:
        mask = self.masker.mask_text
        return ExecResult(ok, action, mask(detail)[:300], mask(error)[:300] if error else None,
                          url=mask(self.page.url), **kw)

    def _fail(self, action: str, exc: BaseException) -> ExecResult:
        name = type(exc).__name__
        if name == "TargetClosedError" or "has been closed" in str(exc) or "Target closed" in str(exc):
            raise BrowserClosed(str(exc)[:120]) from None
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else name
        hint = ""
        if name == "TimeoutError":
            hint = " (not found, not visible, or covered by something)"
        return self._res(False, action, error=f"{name}: {first[:160]}{hint}")

    def _locate(self, snap: Snapshot, ref: str, action: str) -> tuple[Element, Any] | ExecResult:
        el = snap.element(ref)
        if el is None:
            return self._res(False, action, error=f"unknown ref {ref!r}: it is not in the latest snapshot")
        if self.page.url != snap.url:
            return self._res(False, action, error="stale ref: the page address changed since the snapshot")
        return el, self.page.locator("xpath=" + el.xpath)

    async def _settle(self) -> None:
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:  # noqa: BLE001, S110 - best effort; the next snapshot shows the real state
            pass
        await self.page.wait_for_timeout(self.settle_ms)

    async def _adopt_new_tab(self, before: list[Any]) -> bool:
        context = self.page.context
        new = [p for p in context.pages if p not in before]
        if not new:
            return False
        self.page = new[-1]
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001, S110
            pass
        return True

    # ------------------------------------------------------------ actions
    async def click(self, snap: Snapshot, ref: str) -> ExecResult:
        loc = self._locate(snap, ref, "click")
        if isinstance(loc, ExecResult):
            return loc
        el, locator = loc
        if el.disabled:
            return self._res(False, "click", error=f"{el.role} “{el.name[:40]}” is disabled")
        before = list(self.page.context.pages)
        try:
            if await locator.count() == 0:
                return self._res(False, "click", error="stale ref: the element is no longer on the page")
            await locator.click(timeout=self.timeout_ms)
            await self._settle()
            tab = await self._adopt_new_tab(before)
        except Exception as exc:  # noqa: BLE001
            return self._fail("click", exc)
        return self._res(True, "click", f"clicked {el.role} “{el.name[:60]}”" + (" (opened in a new tab; now on it)"
                                                                                   if tab else ""), new_tab=tab)

    async def type(self, snap: Snapshot, ref: str, value: str) -> ExecResult:
        loc = self._locate(snap, ref, "type")
        if isinstance(loc, ExecResult):
            return loc
        el, locator = loc
        if el.role != "field":
            return self._res(False, "type", error=f"{el.role} “{el.name[:40]}” is not a text field")
        if el.type == "password":
            return self._res(False, "type", error="password fields are never typed by the agent")
        if el.readonly or el.disabled:
            return self._res(False, "type", error=f"field “{el.name[:40]}” is read-only or disabled")
        try:
            if await locator.count() == 0:
                return self._res(False, "type", error="stale ref: the element is no longer on the page")
            await locator.fill(value, timeout=self.timeout_ms)
            await self.page.wait_for_timeout(self.settle_ms // 2)
        except Exception as exc:  # noqa: BLE001
            return self._fail("type", exc)
        return self._res(True, "type", f"typed into field “{el.name[:60]}”")  # the value is not echoed

    async def select(self, snap: Snapshot, ref: str, option: str) -> ExecResult:
        loc = self._locate(snap, ref, "select")
        if isinstance(loc, ExecResult):
            return loc
        el, locator = loc
        if el.role != "select":
            return self._res(False, "select", error=f"{el.role} “{el.name[:40]}” is not a dropdown")
        match = next((o for o in el.options if o.strip().lower() == option.strip().lower()), None)
        if match is None:
            return self._res(False, "select", error=f"“{option[:40]}” is not one of: " + " | ".join(el.options[:8]))
        try:
            await locator.select_option(label=match, timeout=self.timeout_ms)
            await self.page.wait_for_timeout(self.settle_ms // 2)
        except Exception as exc:  # noqa: BLE001
            return self._fail("select", exc)
        return self._res(True, "select", f"chose “{match[:60]}” in “{el.name[:40]}”")

    async def navigate(self, url: str) -> ExecResult:
        if urlparse(url).scheme not in ("http", "https"):
            return self._res(False, "navigate", error="only http and https addresses can be opened")
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await self.page.wait_for_timeout(self.settle_ms)
        except Exception as exc:  # noqa: BLE001 - includes addresses the browser-level guard blocked
            failed = self._fail("navigate", exc)
            await self._leave_error_page()
            if "ERR_BLOCKED_BY_CLIENT" in (failed.error or ""):
                failed.error = "blocked: that address is outside the allowed sites"
            failed.url = self.masker.mask_text(self.page.url)
            return failed
        return self._res(True, "navigate", "opened the address")

    async def _leave_error_page(self) -> None:
        """After a blocked or failed navigation Chrome shows an error page; return to the page we were on."""
        try:
            await self.page.wait_for_timeout(300)
            if self.page.url.startswith("chrome-error:"):
                await self.page.go_back(wait_until="domcontentloaded", timeout=5000)
        except Exception:  # noqa: BLE001, S110 - best effort; the next snapshot shows where the tab really is
            pass

    async def scroll(self, direction: str = "down") -> ExecResult:
        if direction not in ("down", "up", "top", "bottom"):
            return self._res(False, "scroll", error="direction must be down, up, top or bottom")
        try:
            y = await self.page.evaluate(
                """(d) => { const h = innerHeight * 0.8;
                  if (d === 'down') scrollBy(0, h); else if (d === 'up') scrollBy(0, -h);
                  else if (d === 'top') scrollTo(0, 0); else scrollTo(0, document.documentElement.scrollHeight);
                  return Math.round(scrollY); }""", direction)
            await self.page.wait_for_timeout(self.settle_ms // 2)
        except Exception as exc:  # noqa: BLE001
            return self._fail("scroll", exc)
        return self._res(True, "scroll", f"scrolled {direction} (now at {y}px)")

    async def inspect(self, snap: Snapshot, ref: str) -> ExecResult:
        """Read one element without changing anything. A field answers only whether it holds an approved value."""
        loc = self._locate(snap, ref, "inspect")
        if isinstance(loc, ExecResult):
            return loc
        el, locator = loc
        if el.type == "password":
            return self._res(False, "inspect", error="password fields are never read")
        try:
            if await locator.count() == 0:
                return self._res(False, "inspect", error="stale ref: the element is no longer on the page")
            if el.is_field:
                keys = await locator.evaluate(_MATCH_JS, self.approved)
                if not el.filled:
                    text = f"field “{el.name[:40]}” is empty"
                elif keys:
                    text = f"field “{el.name[:40]}” holds the approved value: {', '.join(keys)}"
                else:
                    text = f"field “{el.name[:40]}” holds a value that is not one of the approved values"
            else:
                text = (await locator.inner_text(timeout=self.timeout_ms)).strip()[:INSPECT_CHARS]
        except Exception as exc:  # noqa: BLE001
            return self._fail("inspect", exc)
        masked = self.masker.mask_text(text)
        return self._res(True, "inspect", f"read {el.role} “{el.name[:40]}”", text=masked)

    async def back(self) -> ExecResult:
        try:
            resp = await self.page.go_back(wait_until="domcontentloaded", timeout=10_000)
            await self.page.wait_for_timeout(self.settle_ms)
        except Exception as exc:  # noqa: BLE001
            return self._fail("back", exc)
        if resp is None and self.page.url in ("about:blank", ""):
            return self._res(False, "back", error="there is no earlier page in this tab's history")
        return self._res(True, "back", "went back")

    async def wait(self, ms: int = 1500) -> ExecResult:
        ms = max(200, min(int(ms), 5000))
        try:
            await self.page.wait_for_timeout(ms)
        except Exception as exc:  # noqa: BLE001
            return self._fail("wait", exc)
        return self._res(True, "wait", f"waited {ms} ms")

    # A one-shot dispatch used by the agent loop: the action name and its already-validated arguments.
    async def run(self, snap: Snapshot, action: str, *, ref: str | None = None, value: str | None = None,
                  option: str | None = None, url: str | None = None, direction: str | None = None,
                  ms: int | None = None) -> ExecResult:
        if action == "click":
            return await self.click(snap, ref or "")
        if action == "type":
            return await self.type(snap, ref or "", value or "")
        if action == "select":
            return await self.select(snap, ref or "", option or "")
        if action == "navigate":
            return await self.navigate(url or "")
        if action == "scroll":
            return await self.scroll(direction or "down")
        if action == "inspect":
            return await self.inspect(snap, ref or "")
        if action == "back":
            return await self.back()
        if action == "wait":
            return await self.wait(ms or 1500)
        return self._res(False, action, error=f"unknown action {action!r}")


def approved_values(values: Any) -> dict[str, str]:
    """The run's approved non-secret values (`FieldValues`) as {key: value}."""
    return {k: v for k in ("app_name", "homepage_url", "redirect_uri", "description")
            if (v := getattr(values, k, None))}


__all__ = ["BrowserClosed", "ExecResult", "Executor", "approved_values"]
