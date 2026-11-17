"""The IO object the orchestrator talks to when the person is in the browser UI instead of the terminal (D-089).

The backend asks questions through `say`, `choose` and `wait_enter`. In the research phase these are called from a
plain worker thread and may block; in the browser phase they are called inside an asyncio loop, where
`Handoffs._wait` awaits any awaitable. So each method blocks in a thread and returns a coroutine in a loop, and
both wait for the UI's answer through the same `Pending` object.
"""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Any


class Pending:
    """One open question for the person."""

    def __init__(self, kind: str, options: list[str] | None = None) -> None:
        self.kind = kind  # enter | choose | consent
        self.options = options or []
        self.event = threading.Event()
        self.result: Any = None
        self.answered = False

    def resolve(self, value: Any, answered: bool = True) -> None:
        if not self.event.is_set():
            self.result, self.answered = value, answered
            self.event.set()


class WebIO:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pending: Pending | None = None
        self.stopped = False
        self.lines: deque[str] = deque(maxlen=50)  # what the terminal would have printed (kept in memory only)

    # -- the IO protocol the backend uses ---------------------------------
    def say(self, text: str) -> None:
        self.lines.append(text[:500])

    def choose(self, prompt: str, options: list[str]) -> Any:
        return self._deliver(self._open("choose", list(options)), None)

    def wait_enter(self, prompt: str) -> Any:
        return self._deliver(self._open("enter"), False)

    def wait_consent(self) -> str | None:
        """Blocks the worker thread until the person gives (or withholds) consent. Returns the account text."""
        return self._block(self._open("consent"), None)

    # -- the UI side ------------------------------------------------------
    def answer(self, kind: str, value: Any) -> bool:
        """Deliver the person's answer to the open question of this kind. False if there is none."""
        with self._lock:
            p = self.pending
        if p is None or p.kind != kind or p.event.is_set():
            return False
        p.resolve(value)
        return True

    def stop(self) -> bool:
        """Like Ctrl+C at a prompt: the open question gets "no answer" and the run saves itself."""
        with self._lock:
            self.stopped = True
            p = self.pending
        if p is not None:
            p.resolve({"enter": False}.get(p.kind), answered=False)
        return p is not None

    def snapshot(self) -> tuple[str, list[str]] | None:
        with self._lock:
            p = self.pending
        return (p.kind, list(p.options)) if p is not None and not p.event.is_set() else None

    # -- internals --------------------------------------------------------
    def _open(self, kind: str, options: list[str] | None = None) -> Pending:
        p = Pending(kind, options)
        with self._lock:
            self.pending = p
            stopped = self.stopped
        if stopped:
            p.resolve(False if kind == "enter" else None, answered=False)
        return p

    def _finish(self, p: Pending, default: Any) -> Any:
        with self._lock:
            if self.pending is p:
                self.pending = None
        return p.result if p.answered else default

    def _block(self, p: Pending, default: Any) -> Any:
        p.event.wait()
        return self._finish(p, default)

    async def _await(self, p: Pending, default: Any) -> Any:
        await asyncio.get_running_loop().run_in_executor(None, p.event.wait)
        return self._finish(p, default)

    def _deliver(self, p: Pending, default: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._block(p, default)  # a plain worker thread (research phase)
        return self._await(p, default)  # inside the agent's event loop
