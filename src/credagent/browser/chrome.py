"""CredAgent-owned local Chrome process with a persistent profile.

Why not `stagehand.local_browser.launch()`? Observed in the Sprint 0 spike
(docs/DECISIONS.md D-012): Stagehand 4.4.0's close() sends CDP Browser.close and
then immediately SIGTERMs Chrome's whole process group, which lost cookies and
localStorage written shortly before close. Owning the process lets us:
  * shut Chrome down gracefully (Browser.close, then wait for exit) so the
    profile is flushed;
  * keep the visible window open if the CredAgent process exits mid-handoff,
    and re-attach later on the saved CDP port.
Stagehand attaches with `local_browser.connect(cdp_url=...)`.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import websockets

from credagent.state.atomic import mkdir_private

MAC_CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

# Mirrors stagehand 4.4.0 browser._DEFAULT_CHROME_FLAGS (needed for its extension),
# minus nothing. Re-check when upgrading Stagehand.
STAGEHAND_FLAGS = (
    "--disable-features=Translate,OptimizationHints,MediaRouter,DialMediaRouteProvider,"
    "CalculateNativeWinOcclusion,InterestFeedContentSuggestions,"
    "CertificateTransparencyComponentUpdater,AutofillServerCommunication,"
    "PrivacySandboxSettings4,RenderDocument",
    "--disable-component-extensions-with-background-pages",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-client-side-phishing-detection",
    "--disable-sync",
    "--metrics-recording-only",
    "--disable-default-apps",
    "--mute-audio",
    "--no-default-browser-check",
    "--no-first-run",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-background-timer-throttling",
    "--disable-ipc-flooding-protection",
    "--password-store=basic",
    "--use-mock-keychain",
    "--force-fieldtrials=*BackgroundTracing/default/",
    "--disable-hang-monitor",
    "--disable-prompt-on-repost",
    "--disable-domain-reliability",
    "--propagate-iph-for-testing",
    "--enable-unsafe-extension-debugging",
    "--remote-allow-origins=*",
    "--enable-features=WebMCP,WebMCPTesting,DevToolsWebMCPSupport",
)


class ChromeError(Exception):
    pass


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cdp_version(port: int, timeout: float = 0.5) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as r:
            return json.loads(r.read())
    except (OSError, ValueError):
        return None


@dataclass
class ChromeProcess:
    pid: int
    port: int
    profile_dir: Path

    @property
    def cdp_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return cdp_version(self.port) is not None

    @classmethod
    def launch(
        cls,
        profile_dir: Path,
        *,
        headless: bool = False,
        extra_args: list[str] | None = None,
        executable: Path = MAC_CHROME,
        ready_timeout_s: float = 20.0,
    ) -> ChromeProcess:
        if not executable.exists():
            raise ChromeError(f"Chrome not found at {executable}")
        mkdir_private(profile_dir)
        port = free_port()
        args = [
            str(executable), *STAGEHAND_FLAGS, "--window-size=1280,800",
            f"--remote-debugging-port={port}", f"--user-data-dir={profile_dir}",
            *(["--headless"] if headless else []), *(extra_args or []), "about:blank",
        ]
        proc = subprocess.Popen(  # noqa: S603 - fixed executable, no shell
            args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True,  # survives our exit
        )
        deadline = time.monotonic() + ready_timeout_s
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise ChromeError(
                    f"Chrome could not start with the profile {profile_dir} (exit code {proc.returncode}). "
                    "Usually another Chrome window is still using it, e.g. a CredAgent run paused at a handoff. "
                    "Finish or close that window, then try again.")
            if cdp_version(port):
                return cls(pid=proc.pid, port=port, profile_dir=profile_dir)
            time.sleep(0.1)
        proc.terminate()
        raise ChromeError("Chrome did not open its DevTools port in time")

    async def graceful_close(self, timeout_s: float = 15.0) -> str:
        """Ask Chrome to quit via CDP and wait for the process to exit (flushes profile).
        Returns how it ended: 'graceful', 'already_exited', or 'terminated'."""
        if not self.is_running():
            return "already_exited"
        info = cdp_version(self.port)
        ws_url = info.get("webSocketDebuggerUrl") if info else None
        if ws_url:
            try:
                async with websockets.connect(ws_url, max_size=None) as ws:
                    await ws.send(json.dumps({"id": 1, "method": "Browser.close"}))
                    try:
                        await asyncio.wait_for(ws.recv(), 5)
                    except (TimeoutError, websockets.ConnectionClosed):
                        pass
            except (OSError, websockets.WebSocketException):
                pass
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not _pid_alive(self.pid):
                return "graceful"
            await asyncio.sleep(0.2)
        try:
            os.kill(self.pid, signal.SIGTERM)  # main process only, not the group
        except ProcessLookupError:
            return "graceful"
        return "terminated"


def _pid_alive(pid: int) -> bool:
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)  # reap if it is our child
        if waited == pid:
            return False
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
