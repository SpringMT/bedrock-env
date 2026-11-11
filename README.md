# bedrock-env

Generate [Amazon Bedrock short-term API keys](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys.html) from your AWS SSO profile, and keep long-running processes (dev servers, agents, ...) supplied with a fresh key.

[日本語](https://github.com/SpringMT/bedrock-env/blob/main/README.ja.md)

```sh
# One-off: set AWS_BEARER_TOKEN_BEDROCK in the current shell
eval "$(bedrock-env export --profile my-sso-profile)"

# Long-running: run a command, and restart it with a new key before the old one expires
bedrock-env run --profile my-sso-profile -- uv run uvicorn app:app --reload
```

## Why

A short-term Bedrock API key is a SigV4 presigned URL signed with your current AWS credentials. It is generated locally (no API call), and it stops working at whichever comes first:

- the requested lifetime (max 12 hours), or
- the expiry of the credentials that signed it.

With an SSO profile the second limit usually wins: role credentials last as long as the permission set's session duration (often 1 hour). Exporting a key by hand means your dev server starts failing with 403 an hour later.

A running process's environment cannot be changed from outside, so `bedrock-env run` does the next best thing: it supervises the command and restarts it with a new key shortly before the current one expires.

## Install

```sh
uv tool install bedrock-env
# or: pipx install bedrock-env
```

Requires Python 3.10+, macOS or Linux.

## Usage

### `bedrock-env export`

Prints the key so you can load it into your shell.

```sh
eval "$(bedrock-env export --profile my-sso-profile)"          # bash / zsh
bedrock-env export --profile my-sso-profile --format fish | source
bedrock-env export --format dotenv > .env.bedrock
bedrock-env export --format json                              # {"token", "region", "expires_at"}
```

The expiry is printed to stderr.

### `bedrock-env run -- COMMAND...`

Runs `COMMAND` with `AWS_BEARER_TOKEN_BEDROCK` (and `AWS_REGION`, if unset) in its environment. Shortly before the key expires it:

1. generates a new key,
2. sends `SIGTERM` to the command's process group (`SIGKILL` after `--stop-timeout`),
3. starts the command again with the new key.

`SIGINT` / `SIGTERM` / `SIGHUP` sent to `bedrock-env` are forwarded to the command. If the command exits on its own, `bedrock-env` exits with the same status and does not restart it.

| Option | Default | |
| --- | --- | --- |
| `--profile` | `AWS_PROFILE` / default chain | AWS profile to sign with |
| `--region` | `AWS_REGION` / profile `region` | Region the key is valid for |
| `--duration` | `12` | Requested lifetime in hours (capped by the credentials' expiry) |
| `--margin` | `300` | Refresh this many seconds before expiry |
| `--retry-interval` | `60` | Wait between failed refresh attempts |
| `--stop-timeout` | `10` | Seconds between `SIGTERM` and `SIGKILL` on restart |
| `--auto-login` | off | Run `aws sso login` when the SSO session has expired |

### When the SSO session expires

The SSO session itself (`aws sso login`) also has a lifetime. Once it expires no new role credentials can be obtained:

- `bedrock-env run` keeps the current process running (its key may still be valid for a few minutes), logs `run aws sso login`, and retries every `--retry-interval`. As soon as you log in from another terminal, the next retry picks up the new session.
- With `--auto-login`, it runs `aws sso login --profile ...` itself, which opens a browser.

## Caveats

- **Restarts are not zero-downtime.** Requests in flight during a restart fail. With SSO this happens about once per permission set session duration.
- The key is bound to a single region.
- Only processes started by `bedrock-env run` get the new key. Shells where you ran `export` need to run it again.
- Windows is not supported (process groups and POSIX signals are used).

If your application uses an AWS SDK directly, you may not need an API key at all: the SDK can sign requests with your SSO profile (SigV4) and refreshes credentials itself. API keys are mainly useful for tools and SDKs that only accept a bearer token.

## Development

```sh
uv sync
uv run pytest
```

## License

MIT
