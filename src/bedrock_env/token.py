"""Generate Amazon Bedrock short-term API keys from the AWS credential chain."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import botocore.session
from aws_bedrock_token_generator import provide_token
from botocore import exceptions as botocore_exceptions

MAX_DURATION = timedelta(hours=12)


class TokenError(Exception):
    """Token could not be generated."""


class LoginRequiredError(TokenError):
    """The SSO session has expired and `aws sso login` is required."""


# Exceptions botocore raises when the SSO access token is missing or expired.
_SSO_LOGIN_ERRORS = tuple(
    getattr(botocore_exceptions, name)
    for name in (
        "UnauthorizedSSOTokenError",
        "SSOTokenLoadError",
        "TokenRetrievalError",
        "LoginTokenLoadError",
    )
    if hasattr(botocore_exceptions, name)
)


@dataclass(frozen=True)
class Token:
    value: str
    region: str
    expires_at: datetime

    def seconds_left(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (self.expires_at - now).total_seconds()


class _StaticProvider:
    """Credential provider that returns already-resolved credentials."""

    def __init__(self, credentials):
        self._credentials = credentials

    def load(self):
        return self._credentials


def resolve_region(session: botocore.session.Session, region: str | None) -> str:
    region = (
        region
        or os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or session.get_config_variable("region")
    )
    if not region:
        raise TokenError(
            "No region configured. Pass --region, set AWS_REGION, or set `region` in the profile."
        )
    return region


def generate_token(
    profile: str | None = None,
    region: str | None = None,
    duration: timedelta = MAX_DURATION,
) -> Token:
    """Generate a short-term Bedrock API key.

    The key stops working when either `duration` passes or the credentials that signed it
    expire, whichever comes first. For SSO profiles the latter is usually the binding limit
    (the permission set's session duration).
    """
    if not timedelta(0) < duration <= MAX_DURATION:
        raise TokenError("Duration must be greater than 0 and at most 12 hours.")

    # A fresh session on every call so botocore does not hand back cached role credentials
    # that are about to expire.
    try:
        session = botocore.session.Session(profile=profile)
        region = resolve_region(session, region)
        credentials = session.get_credentials()
        if credentials is None:
            raise TokenError("No AWS credentials found.")
        frozen = credentials.get_frozen_credentials()
    except _SSO_LOGIN_ERRORS as e:
        raise LoginRequiredError(str(e)) from e
    except botocore_exceptions.ProfileNotFound as e:
        raise TokenError(str(e)) from e
    except (botocore_exceptions.BotoCoreError, botocore_exceptions.ClientError) as e:
        raise TokenError(str(e)) from e

    now = datetime.now(timezone.utc)
    expires_at = now + duration
    # RefreshableCredentials (SSO, AssumeRole, ...) know their own expiry. There is no public
    # accessor, so read the private attribute defensively.
    credential_expiry = getattr(credentials, "_expiry_time", None)
    if isinstance(credential_expiry, datetime):
        if credential_expiry.tzinfo is None:
            credential_expiry = credential_expiry.replace(tzinfo=timezone.utc)
        expires_at = min(expires_at, credential_expiry)

    signed_for = expires_at - now
    if signed_for.total_seconds() < 1:
        raise TokenError("The underlying AWS credentials have already expired.")

    value = provide_token(
        region=region,
        aws_credentials_provider=_StaticProvider(frozen),
        expiry=timedelta(seconds=int(signed_for.total_seconds())),
    )
    return Token(value=value, region=region, expires_at=expires_at)
