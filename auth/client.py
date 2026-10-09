"""Headless Supabase adapter. No documents or production metadata leave the app."""
from __future__ import annotations

from .config import AuthConfig
from .model import Approval, AuthResult, Outcome, timestamp


class AccessClient:
    def __init__(self, config: AuthConfig, *, factory=None):
        self.config = config
        self.factory = factory

    def _create(self, http):
        if self.factory:
            return self.factory(http)
        from supabase import ClientOptions, create_client
        return create_client(self.config.url, self.config.publishable_key, options=ClientOptions(
            auto_refresh_token=False, persist_session=False,
            httpx_client=http, postgrest_client_timeout=10,
        ))

    def _access(self, client, session, previous=None) -> AuthResult:
        if session is None or not session.access_token or not session.refresh_token:
            return AuthResult(Outcome.RELOGIN, "Sign in again to restore online verification.")
        # get_user performs server validation; JWT claims/local cached session alone are insufficient.
        response = client.auth.get_user(session.access_token)
        user = response.user
        if user is None or not user.id or (previous and user.id != previous.user_id):
            return AuthResult(Outcome.RELOGIN, "The server could not confirm this account.")
        rows = client.table("app_access").select("user_id,is_active").eq("user_id", user.id).execute().data
        if not isinstance(rows, list) or len(rows) > 1:
            return AuthResult(Outcome.UNAVAILABLE, "Online verification is temporarily unavailable.")
        if rows:
            row = rows[0]
            if not isinstance(row, dict) or row.get("user_id") != user.id or type(row.get("is_active")) is not bool:
                return AuthResult(Outcome.UNAVAILABLE, "Online verification is temporarily unavailable.")
        if not rows or rows[0]["is_active"] is False:
            return AuthResult(Outcome.REVOKED if previous else Outcome.DENIED,
                              "This account is not approved for PDFDocuEdit Pro.")
        now = timestamp()
        approval = Approval(self.config.project_ref, user.id, user.email or "", session.refresh_token,
                            previous.approved_at if previous else now, now)
        approval.validate(self.config.project_ref)
        return AuthResult(Outcome.APPROVED, "Account verified online.", approval)

    def _request(self, operation, *, signing_in=False) -> AuthResult:
        import httpx
        try:
            # SDK session persistence/background refresh are disabled. One owned HTTP client per request.
            with httpx.Client(timeout=httpx.Timeout(10), follow_redirects=False) as http:
                client = self._create(http)
                return operation(client)
        except Exception as error:
            # Never log SDK errors: responses may contain account/session data.
            status = getattr(error, "status", None)
            if status in (400, 401, 403, "400", "401", "403"):
                return AuthResult(Outcome.DENIED if signing_in else Outcome.RELOGIN,
                                  "Email or password is incorrect." if signing_in else
                                  "Sign in again to restore online verification. Offline approval is retained.")
            return AuthResult(Outcome.UNAVAILABLE, "Cannot verify online. Check your connection and try again.")

    def sign_in(self, email: str, password: str) -> AuthResult:
        return self._request(lambda client: self._access(client, client.auth.sign_in_with_password(
            {"email": email, "password": password}).session), signing_in=True)

    def verify(self, approval: Approval) -> AuthResult:
        return self._request(lambda client: self._access(client, client.auth.refresh_session(
            approval.refresh_token).session, approval))
