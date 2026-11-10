import sys
from datetime import datetime, timedelta, timezone

from bedrock_env.runner import ENV_TOKEN, Runner
from bedrock_env.token import LoginRequiredError, Token

# Child that appends the token it was started with to a file, then waits for a signal.
CHILD = (
    "import os, sys, time\n"
    "open(sys.argv[1], 'a').write(os.environ['" + ENV_TOKEN + "'] + '\\n')\n"
    "time.sleep(60)\n"
)


def token(name: str, seconds: float) -> Token:
    return Token(name, "us-east-1", datetime.now(timezone.utc) + timedelta(seconds=seconds))


def sequence(*steps):
    """Generator returning each step in turn; exceptions are raised, callables called."""
    calls = iter(steps)

    def generate():
        step = next(calls)
        if isinstance(step, Exception):
            raise step
        return step() if callable(step) else step

    return generate


def started_tokens(path):
    return path.read_text().split() if path.exists() else []


def run(tmp_path, generate, **kwargs):
    out = tmp_path / "tokens"
    # Stop the loop once the generator is exhausted.
    def guarded():
        try:
            return generate()
        except StopIteration:
            raise KeyboardInterrupt

    runner = Runner(
        [sys.executable, "-c", CHILD, str(out)],
        guarded,
        margin=0.5,
        retry_interval=0.3,
        stop_timeout=2,
        **kwargs,
    )
    try:
        runner.run()
    except KeyboardInterrupt:
        pass
    finally:
        if runner.child and runner.child.poll() is None:
            runner._stop()
    return started_tokens(out)


def test_restarts_with_new_token_before_expiry(tmp_path):
    tokens = run(
        tmp_path,
        sequence(lambda: token("a", 1.0), lambda: token("b", 1.0), lambda: token("c", 1.0)),
    )
    assert tokens == ["a", "b", "c"]


def test_keeps_child_running_when_sso_login_required(tmp_path):
    tokens = run(
        tmp_path,
        sequence(
            lambda: token("a", 1.0),
            LoginRequiredError("expired"),
            LoginRequiredError("expired"),
            lambda: token("b", 1.0),
        ),
    )
    assert tokens == ["a", "b"]


def test_does_not_restart_when_expiry_did_not_advance(tmp_path):
    first = token("a", 1.0)
    stale = Token("stale", first.region, first.expires_at)
    tokens = run(tmp_path, sequence(first, stale, lambda: token("b", 1.0)))
    assert tokens == ["a", "b"]


def test_auto_login_retries_immediately(tmp_path):
    logins = []
    tokens = run(
        tmp_path,
        sequence(lambda: token("a", 1.0), LoginRequiredError("expired"), lambda: token("b", 1.0)),
        on_login_required=lambda: logins.append(1),
    )
    assert tokens == ["a", "b"]
    assert logins == [1]


def test_returns_child_exit_code_without_restart(tmp_path):
    runner = Runner(
        [sys.executable, "-c", "import sys; sys.exit(3)"],
        sequence(token("a", 60)),
        margin=0.5,
    )
    assert runner.run() == 3


def test_keeps_child_running_on_unexpected_error(tmp_path):
    tokens = run(
        tmp_path,
        sequence(lambda: token("a", 1.0), RuntimeError("boom"), lambda: token("b", 1.0)),
    )
    assert tokens == ["a", "b"]
