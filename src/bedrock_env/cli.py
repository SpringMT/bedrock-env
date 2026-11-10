"""Command line interface for bedrock-env."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from datetime import timedelta
from functools import partial

from . import __version__
from .runner import ENV_TOKEN, Runner, log
from .token import LoginRequiredError, TokenError, generate_token


def _add_aws_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--profile", help="AWS profile to sign with (default: AWS_PROFILE / default chain)")
    parser.add_argument("--region", help="Region the key is valid for (default: AWS_REGION / profile)")
    parser.add_argument(
        "--duration",
        type=float,
        default=12,
        metavar="HOURS",
        help="Requested lifetime in hours, max 12 (capped by the credentials' own expiry)",
    )


def _generator(args: argparse.Namespace):
    return partial(
        generate_token,
        profile=args.profile,
        region=args.region,
        duration=timedelta(hours=args.duration),
    )


def _sso_login(profile: str | None) -> None:
    command = ["aws", "sso", "login"] + (["--profile", profile] if profile else [])
    log(f"running `{shlex.join(command)}`")
    subprocess.run(command, check=False)


def cmd_export(args: argparse.Namespace) -> int:
    token = _generator(args)()
    expires = token.expires_at.isoformat(timespec="seconds")
    if args.format == "json":
        print(json.dumps({"token": token.value, "region": token.region, "expires_at": expires}))
    elif args.format == "dotenv":
        print(f"{ENV_TOKEN}={token.value}")
    elif args.format == "fish":
        print(f"set -gx {ENV_TOKEN} {shlex.quote(token.value)};")
    else:
        print(f"export {ENV_TOKEN}={shlex.quote(token.value)}")
    if args.format != "json":
        print(f"# key for {token.region}, valid until {expires}", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        print("bedrock-env run: missing command (usage: bedrock-env run -- <command> ...)", file=sys.stderr)
        return 2
    runner = Runner(
        command,
        _generator(args),
        margin=args.margin,
        retry_interval=args.retry_interval,
        stop_timeout=args.stop_timeout,
        on_login_required=partial(_sso_login, args.profile) if args.auto_login else None,
    )
    code = runner.run()
    # Popen reports death-by-signal as -N; shells use 128 + N.
    return 128 - code if code < 0 else code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bedrock-env",
        description="Generate Amazon Bedrock short-term API keys and keep them fresh.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    export = sub.add_parser(
        "export",
        help="print a key as shell exports",
        description=f'Print {ENV_TOKEN}. Use as: eval "$(bedrock-env export)"',
    )
    _add_aws_options(export)
    export.add_argument("--format", choices=["sh", "fish", "dotenv", "json"], default="sh")
    export.set_defaults(func=cmd_export)

    run = sub.add_parser(
        "run",
        help="run a command with a key and restart it before the key expires",
        description=f"Run COMMAND with {ENV_TOKEN} set, regenerating the key and restarting "
        "COMMAND shortly before it expires.",
    )
    _add_aws_options(run)
    run.add_argument(
        "--margin",
        type=float,
        default=300,
        metavar="SECONDS",
        help="refresh this many seconds before expiry (default: 300)",
    )
    run.add_argument(
        "--retry-interval",
        type=float,
        default=60,
        metavar="SECONDS",
        help="wait between failed refresh attempts (default: 60)",
    )
    run.add_argument(
        "--stop-timeout",
        type=float,
        default=10,
        metavar="SECONDS",
        help="wait this long after SIGTERM before SIGKILL on restart (default: 10)",
    )
    run.add_argument(
        "--auto-login",
        action="store_true",
        help="run `aws sso login` automatically when the SSO session has expired",
    )
    run.add_argument("command", nargs=argparse.REMAINDER, help="command to run (after --)")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LoginRequiredError as e:
        profile = f" --profile {args.profile}" if args.profile else ""
        print(f"bedrock-env: SSO session expired. Run `aws sso login{profile}`.\n  ({e})", file=sys.stderr)
        return 1
    except TokenError as e:
        print(f"bedrock-env: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
