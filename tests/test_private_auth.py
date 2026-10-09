from __future__ import annotations

import json
import sys
import threading
import time
import types
from dataclasses import replace
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from auth.client import AccessClient
from auth.config import AuthConfig, configuration
from auth.controller import AuthController
from auth.model import Approval, AuthResult, Outcome, timestamp
from auth.store import ApprovalStore, StorageError

CONFIG = AuthConfig("testproject", "https://testproject.supabase.co", "sb_publishable_public_test")
USER = "f63613d9-81b8-4a36-b765-a37b6e9e0916"


def approval(**changes):
    now = timestamp()
    return replace(Approval(CONFIG.project_ref, USER, "test@example.invalid", "PRIVATE_REFRESH", now, now), **changes)


class MemoryBackend:
    def __init__(self):
        self.value = None

    def get_password(self, service, username):
        return self.value

    def set_password(self, service, username, value):
        self.value = value

    def delete_password(self, service, username):
        self.value = None


def test_secure_store_roundtrip_and_corrupt_fail_closed():
    backend = MemoryBackend()
    store = ApprovalStore(CONFIG.project_ref, backend=backend)
    store.save(approval())
    assert store.load() == approval(approved_at=store.load().approved_at, last_verified=store.load().last_verified)
    assert "PRIVATE_REFRESH" not in repr(store.load())
    for invalid in ("{", json.dumps({"refresh_token": "token"}), json.dumps({**json.loads(backend.value), "project_ref": "other"})):
        backend.value = invalid
        assert store.load() is None
    store.clear()
    assert backend.value is None


def test_storage_error_never_exposes_backend_exception():
    class Failing(MemoryBackend):
        def set_password(self, *args):
            raise RuntimeError("SECRET_TOKEN")
    with pytest.raises(StorageError) as caught:
        ApprovalStore(CONFIG.project_ref, backend=Failing()).save(approval())
    assert "SECRET_TOKEN" not in str(caught.value)


def test_frozen_auth_cannot_be_disabled_with_environment(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("PDFDOCUEDIT_ENABLE_AUTH", "0")
    module = types.ModuleType("pdfdocuedit_auth_build")
    module.PROJECT = vars(CONFIG)
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert configuration() == CONFIG
    module.PROJECT = {**vars(CONFIG), "url": "http://testproject.supabase.co"}
    with pytest.raises(ValueError):
        configuration()


def test_public_build_is_auth_off(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.delenv("PDFDOCUEDIT_ENABLE_AUTH", raising=False)
    assert configuration() is None


class FakeSDK:
    def __init__(self, rows, *, user=USER, failure=None):
        self.rows, self.user, self.failure = rows, user, failure
        self.auth = self
        self.calls = []
        self.session = NS(access_token="SECRET_ACCESS", refresh_token="SECRET_REFRESH")

    def sign_in_with_password(self, credentials):
        self.calls.append("sign-in")
        return NS(session=self.session)

    def refresh_session(self, token):
        self.calls.append("refresh")
        if self.failure:
            raise self.failure
        return NS(session=self.session)

    def get_user(self, token):
        self.calls.append("server-user")
        return NS(user=NS(id=self.user, email="test@example.invalid"))

    def table(self, name):
        assert name == "app_access"
        self.calls.append("access-row")
        return self

    def select(self, fields):
        assert fields == "user_id,is_active"
        return self

    def eq(self, field, value):
        assert field == "user_id" and value == self.user
        return self

    def execute(self):
        return NS(data=self.rows)


@pytest.mark.parametrize("rows,outcome", [
    ([{"user_id": USER, "is_active": True}], Outcome.APPROVED),
    ([{"user_id": USER, "is_active": False}], Outcome.REVOKED),
    ([], Outcome.REVOKED),
    (None, Outcome.UNAVAILABLE),
    ([{"user_id": USER, "is_active": "true"}], Outcome.UNAVAILABLE),
    ([{"user_id": "another", "is_active": False}], Outcome.UNAVAILABLE),
])
def test_verified_identity_required_before_revocation(rows, outcome):
    sdk = FakeSDK(rows)
    result = AccessClient(CONFIG, factory=lambda http: sdk).verify(approval())
    assert result.outcome == outcome
    assert sdk.calls == ["refresh", "server-user", "access-row"]
    assert "SECRET" not in repr(result)


def test_identity_mismatch_is_not_confirmed_revocation():
    sdk = FakeSDK([], user=str(uuid4()))
    assert AccessClient(CONFIG, factory=lambda http: sdk).verify(approval()).outcome == Outcome.RELOGIN
    assert "access-row" not in sdk.calls


@pytest.mark.parametrize("status,outcome", [(401, Outcome.RELOGIN), (500, Outcome.UNAVAILABLE), (None, Outcome.UNAVAILABLE)])
def test_session_or_network_failure_keeps_offline_authorization(status, outcome):
    error = RuntimeError("SECRET_REFRESH_TOKEN_AND_ACCOUNT")
    error.status = status
    sdk = FakeSDK([], failure=error)
    result = AccessClient(CONFIG, factory=lambda http: sdk).verify(approval())
    assert result.outcome == outcome
    assert "SECRET" not in result.message


def pump(app, condition, seconds=3):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert condition()


def test_controller_offline_retained_and_single_flight(qt_application):
    backend = MemoryBackend()
    store = ApprovalStore(CONFIG.project_ref, backend=backend)
    original = approval(approved_at="2020-01-01T00:00:00+00:00", last_verified="2020-01-01T00:00:00+00:00")
    store.save(original)
    started, release = threading.Event(), threading.Event()

    class Client:
        def verify(self, value):
            started.set()
            release.wait(3)
            return AuthResult(Outcome.UNAVAILABLE, "Offline")
    controller = AuthController(Client(), store)
    admitted = []
    controller.approved.connect(admitted.append)
    controller.start()
    assert admitted == [original]
    pump(qt_application, started.is_set)
    assert not controller.check()
    release.set()
    pump(qt_application, lambda: not controller.busy)
    assert controller.approval == original and store.load() == original
    controller.stop()


def test_signout_rejects_late_verification(qt_application):
    backend = MemoryBackend()
    store = ApprovalStore(CONFIG.project_ref, backend=backend)
    store.save(approval())
    release = threading.Event()
    class Client:
        def verify(self, value):
            release.wait(3)
            return AuthResult(Outcome.APPROVED, "Verified", value)
    controller = AuthController(Client(), store)
    controller.start()
    pump(qt_application, lambda: controller.busy)
    controller.sign_out()
    release.set()
    pump(qt_application, lambda: not controller.busy)
    assert controller.approval is None and store.load() is None
    controller.stop()


def test_controller_revocation_clears_credential(qt_application):
    backend = MemoryBackend()
    store = ApprovalStore(CONFIG.project_ref, backend=backend)
    store.save(approval())
    controller = AuthController(NS(verify=lambda value: AuthResult(Outcome.REVOKED, "Revoked")), store)
    revoked = []
    controller.revoked.connect(revoked.append)
    controller.start()
    pump(qt_application, lambda: bool(revoked) and not controller.busy)
    assert controller.approval is None and store.load() is None
    controller.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows credential backend")
def test_actual_windows_credential_manager_roundtrip():
    # Isolated QA namespace, never touches the real project approval.
    store = ApprovalStore("qa" + uuid4().hex)
    value = approval(project_ref=store.project_ref)
    try:
        store.save(value)
        assert store.load() == value
    finally:
        store.clear()
    assert store.load() is None
    store.blocked_path.unlink(missing_ok=True)
    store.blocked_path.parent.rmdir()


def test_failed_credential_deletion_blocks_restart_until_new_signin(tmp_path):
    class RefuseDeletion(MemoryBackend):
        def delete_password(self, *args):
            raise RuntimeError("PRIVATE_REFRESH")
    backend = RefuseDeletion()
    marker = tmp_path / "qa/require-signin"
    store = ApprovalStore(CONFIG.project_ref, backend=backend, blocked_path=marker)
    store.save(approval())
    with pytest.raises(StorageError, match="blocked until sign-in"):
        store.clear()
    assert marker.read_bytes() == b""
    assert backend.value is not None
    assert ApprovalStore(CONFIG.project_ref, backend=backend, blocked_path=marker).load() is None
    store.save(approval())
    assert not marker.exists() and store.load() is not None
