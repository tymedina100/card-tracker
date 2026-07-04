import httpx
import pytest

from cardtracker.config import Settings
from cardtracker.ebay_auth import EbayTokenProvider, MissingCredentialsError


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_missing_credentials_gives_clear_error():
    provider = EbayTokenProvider(Settings())
    with pytest.raises(MissingCredentialsError, match="EBAY_CLIENT_ID"):
        provider.get_token()


def test_token_fetch_and_caching(settings_with_creds):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.path == "/identity/v1/oauth2/token"
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"access_token": "tok-1", "expires_in": 7200})

    provider = EbayTokenProvider(settings_with_creds, client=make_client(handler))
    assert provider.get_token() == "tok-1"
    assert provider.get_token() == "tok-1"
    assert len(calls) == 1


def test_expired_token_refetched(settings_with_creds):
    tokens = iter(["tok-1", "tok-2"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": next(tokens), "expires_in": 7200})

    provider = EbayTokenProvider(settings_with_creds, client=make_client(handler))
    assert provider.get_token() == "tok-1"
    provider._expires_at = 0  # force expiry
    assert provider.get_token() == "tok-2"


def test_sandbox_endpoint_used_by_default(settings_with_creds):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        body = request.content.decode()
        seen["grant"] = "grant_type=client_credentials" in body
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 7200})

    EbayTokenProvider(settings_with_creds, client=make_client(handler)).get_token()
    assert seen["host"] == "api.sandbox.ebay.com"
    assert seen["grant"]


def test_http_error_propagates(settings_with_creds):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    provider = EbayTokenProvider(settings_with_creds, client=make_client(handler))
    with pytest.raises(httpx.HTTPStatusError):
        provider.get_token()
