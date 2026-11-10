"""Run a command with a Bedrock API key and restart it before the key expires."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime

from .token import LoginRequiredError, Token, TokenError

ENV_TOKEN = "AWS_BEARER_TOKEN_BEDROCK"
_FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[bedrock-env {stamp}] {message}", file=sys.stderr, flush=True)


def build_env(token: Token, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    env[ENV_TOKEN] = token.value
    # The key is bound to the region it was signed for.
    env.setdefault("AWS_REGION", token.region)
    return env


class Runner:
    def __init__(
        self,
        command: Sequence[str],
        generate: Callable[[], Token],
        *,
        margin: float = 300,
        retry_interval: float = 60,
        stop_timeout: float = 10,
        on_login_required: Callable[[], None] | None = None,
    ):
        self.command = list(command)
        self.generate = generate
        self.margin = margin
        self.retry_interval = retry_interval
        self.stop_timeout = stop_timeout
        self.on_login_required = on_login_required
        self.child: subprocess.Popen | None = None
        self._stopping = False

    # -- child process -------------------------------------------------------

    def _start(self, token: Token) -> None:
        # Own process group so restarts reach every descendant (e.g. `uv run` -> uvicorn).
        self.child = subprocess.Popen(self.command, env=build_env(token), start_new_session=True)
        log(f"started pid {self.child.pid}; key valid until {_local(token.expires_at)}")

    def _signal_child(self, sig: int) -> None:
        if self.child is None or self.child.poll() is not None:
            return
        try:
            os.killpg(self.child.pid, sig)
        except ProcessLookupError:
            pass

    def _stop(self) -> int:
        assert self.child is not None
        self._signal_child(signal.SIGTERM)
        try:
            return self.child.wait(timeout=self.stop_timeout)
        except subprocess.TimeoutExpired:
            log(f"pid {self.child.pid} did not exit in {self.stop_timeout:g}s; sending SIGKILL")
            self._signal_child(signal.SIGKILL)
            return self.child.wait()

    def _handle_signal(self, signum, _frame) -> None:
        self._stopping = True
        self._signal_child(signum)

    # -- main loop -----------------------------------------------------------

    def _wait_child(self, seconds: float) -> int | None:
        """Wait up to `seconds` for the child to exit. Returns its exit code if it did."""
        assert self.child is not None
        deadline = time.monotonic() + max(seconds, 0)
        while True:
            remaining = deadline - time.monotonic()
            try:
                return self.child.wait(timeout=max(min(remaining, 1.0), 0))
            except subprocess.TimeoutExpired:
                if remaining <= 0:
                    return None

    def _try_generate(self) -> Token | None:
        try:
            return self.generate()
        except LoginRequiredError:
            log("SSO session expired; run `aws sso login` (the current process keeps running)")
            if self.on_login_required:
                self.on_login_required()
                try:
                    return self.generate()
                except Exception as e:
                    log(f"failed to refresh key after login: {e}")
        except TokenError as e:
            log(f"failed to refresh key: {e}")
        except Exception as e:
            # Never let a refresh failure take the running process down with us.
            log(f"unexpected error refreshing key: {e!r}")
        return None

    def run(self) -> int:
        token = self.generate()  # Fail fast on startup.
        previous = {s: signal.signal(s, self._handle_signal) for s in _FORWARDED_SIGNALS}
        try:
            self._start(token)
            while True:
                # If the credentials live shorter than the margin, refresh halfway instead of
                # restarting in a tight loop.
                left = token.seconds_left()
                wait = max(left - self.margin, left / 2)
                code = self._wait_child(wait)
                if code is not None:
                    return code
                if self._stopping:
                    return self.child.wait()

                new = self._try_generate()
                if new is None or new.expires_at <= token.expires_at:
                    if new is not None:
                        log("credentials were not renewed yet; retrying")
                    code = self._wait_child(self.retry_interval)
                    if code is not None:
                        return code
                    continue

                log("refreshing key; restarting process")
                self._stop()
                if self._stopping:
                    return 0
                token = new
                self._start(token)
        finally:
            if self.child is not None and self.child.poll() is None:
                self._stop()
            for s, handler in previous.items():
                signal.signal(s, handler)


def _local(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
