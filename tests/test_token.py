import base64
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import pytest
from botocore.credentials import Credentials
from botocore.exceptions import UnauthorizedSSOTokenError

from bedrock_env import token as token_module
from bedrock_env.token import LoginRequiredError, TokenError, generate_token


class FakeCredentials:
    def __init__(self, expiry=None, error=None):
        self._expiry_time = expiry
        self._error = error

    def get_frozen_credentials(self):
        if self._error:
            raise self._error
        return Credentials("AKIDEXAMPLE", "secret", "session-token").get_frozen_credentials()


class FakeSession:
    credentials = None
    region = "us-west-2"

    def __init__(self, profile=None):
        self.profile = profile

    def get_credentials(self):
        return self.credentials

    def get_config_variable(self, name):
        return self.region if name == "region" else None


@pytest.fixture
def session(monkeypatch):
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setattr(token_module.botocore.session, "Session", FakeSession)
    FakeSession.credentials = FakeCredentials()
    FakeSession.region = "us-west-2"
    return FakeSession


def signed_expires(value: str) -> int:
    url = base64.b64decode(value.removeprefix("bedrock-api-key-")).decode()
    return int(parse_qs(url.split("?", 1)[1])["X-Amz-Expires"][0])


def test_expiry_capped_by_credentials(session):
    expiry = datetime.now(timezone.utc) + timedelta(hours=1)
    session.credentials = FakeCredentials(expiry=expiry)
    token = generate_token(duration=timedelta(hours=12))
    assert token.expires_at == expiry
    assert token.region == "us-west-2"
    assert 3590 <= signed_expires(token.value) <= 3600


def test_expiry_uses_duration_for_static_credentials(session):
    token = generate_token(duration=timedelta(hours=2))
    assert signed_expires(token.value) == 7200


def test_region_from_environment_wins(session, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-northeast-1")
    assert generate_token().region == "ap-northeast-1"


def test_missing_region(session):
    session.region = None
    with pytest.raises(TokenError, match="region"):
        generate_token()


def test_sso_login_required(session):
    session.credentials = FakeCredentials(error=UnauthorizedSSOTokenError())
    with pytest.raises(LoginRequiredError):
        generate_token()


def test_invalid_duration(session):
    with pytest.raises(TokenError):
        generate_token(duration=timedelta(hours=13))
