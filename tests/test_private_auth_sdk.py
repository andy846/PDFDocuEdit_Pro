from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest

from auth.client import AccessClient
from auth.config import AuthConfig
from auth.model import Approval, Outcome, timestamp

USER = "f63613d9-81b8-4a36-b765-a37b6e9e0916"
CONFIG = AuthConfig("sdkfixture", "https://sdkfixture.supabase.co", "sb_publishable_test")


@pytest.mark.parametrize("active,outcome", [(True, Outcome.APPROVED), (False, Outcome.REVOKED)])
def test_pinned_sdk_refresh_identity_and_rls_authorization(active, outcome):
    calls = []
    token = jwt.encode({"sub": USER, "exp": int(time.time()) + 3600, "aud": "authenticated"}, "fixture-key-for-tests-never-production-123", algorithm="HS256")
    user = {"id": USER, "aud": "authenticated", "email": "fixture@example.invalid",
            "created_at": "2026-01-01T00:00:00Z", "app_metadata": {}, "user_metadata": {}}

    def handle(request):
        calls.append(request.url.path)
        assert request.headers["apikey"] == CONFIG.publishable_key
        if request.url.path == "/auth/v1/token":
            assert request.url.params["grant_type"] == "refresh_token"
            assert json.loads(request.content) == {"refresh_token": "old-refresh"}
            return httpx.Response(200, json={"access_token": token, "refresh_token": "new-refresh",
                                          "expires_in": 3600, "token_type": "bearer", "user": user})
        assert request.headers["authorization"] == "Bearer " + token
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json=user)
        assert request.url.path == "/rest/v1/app_access"
        assert request.url.params["user_id"] == "eq." + USER
        return httpx.Response(200, json=[{"user_id": USER, "is_active": active}])

    client = AccessClient(CONFIG, http_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handle), **kwargs))
    now = timestamp()
    result = client.verify(Approval(CONFIG.project_ref, USER, user["email"], "old-refresh", now, now))
    assert result.outcome == outcome
    assert calls == ["/auth/v1/token", "/auth/v1/user", "/rest/v1/app_access"]
    if active:
        assert result.approval.refresh_token == "new-refresh"


def test_pinned_sdk_rejects_wrong_password_without_exposing_server_body():
    def handle(request):
        return httpx.Response(400, json={"code": "invalid_credentials", "msg": "SECRET_ERROR_BODY"})
    client = AccessClient(CONFIG, http_factory=lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handle), **kwargs))
    result = client.sign_in("fixture@example.invalid", "private-password")
    assert result.outcome == Outcome.DENIED
    assert "SECRET" not in repr(result) and "private-password" not in repr(result)
