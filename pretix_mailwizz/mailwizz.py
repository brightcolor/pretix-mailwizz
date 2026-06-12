"""
Minimal MailWizz API client.

Only implements what the plugin needs:
  * search a subscriber by email in a list
  * create a subscriber in a list (which triggers MailWizz's double opt-in
    if the list is configured for it)
  * a lightweight connection test

Privacy rules enforced here:
  * The API key is sent in headers only and never appears in log output.
  * Email addresses are masked in all log messages.
  * Full API response bodies are never logged (they may contain
    personal data); only status codes and MailWizz error summaries are.
"""
import logging
from typing import Optional

import requests

from .config import mask_email

logger = logging.getLogger(__name__)

# Subscriber status values as returned by the MailWizz API
STATUS_CONFIRMED = "confirmed"
STATUS_UNCONFIRMED = "unconfirmed"
STATUS_UNSUBSCRIBED = "unsubscribed"
STATUS_BLACKLISTED = "blacklisted"


class MailWizzError(Exception):
    """Permanent error – retrying will not help (bad config, 4xx, ...)."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class MailWizzTransientError(MailWizzError):
    """Temporary error – worth retrying (network, timeout, 5xx)."""


class MailWizzAlreadySubscribedError(MailWizzError):
    """MailWizz reported that the subscriber already exists in the list."""


class MailWizzClient:
    def __init__(
        self,
        api_url: str,
        api_key: str,
        timeout: int = 10,
        debug: bool = False,
        session: Optional[requests.Session] = None,
    ):
        self.api_url = api_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self.debug = debug
        self.session = session or requests.Session()

    @classmethod
    def from_event(cls, event) -> "MailWizzClient":
        """Build a client from event settings (with organizer fallback)."""
        from .config import (
            DEFAULT_TIMEOUT,
            K_API_KEY,
            K_API_URL,
            K_DEBUG,
            K_TIMEOUT,
            get_bool,
            get_int,
        )
        s = event.settings
        return cls(
            api_url=(s.get(K_API_URL) or "").strip(),
            api_key=(s.get(K_API_KEY) or "").strip(),
            timeout=get_int(s, K_TIMEOUT, DEFAULT_TIMEOUT),
            debug=get_bool(s, K_DEBUG, default=False),
        )

    # ── HTTP layer ────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        return {
            # MailWizz 2.x single-key authentication
            "X-Api-Key": self._api_key,
            # MailWizz 1.x compatibility (public key header)
            "X-MW-PUBLIC-KEY": self._api_key,
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, data: Optional[dict] = None,
                 params: Optional[dict] = None) -> dict:
        url = f"{self.api_url}/{path.lstrip('/')}"
        try:
            resp = self.session.request(
                method,
                url,
                headers=self._headers(),
                data=data,
                params=params,
                timeout=self.timeout,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            raise MailWizzTransientError(
                f"MailWizz unreachable: {type(e).__name__}"
            ) from e
        except requests.RequestException as e:
            raise MailWizzError(f"MailWizz request failed: {type(e).__name__}") from e

        if self.debug:
            # Data-minimal debug logging: method, path, status code only.
            logger.debug("MailWizz %s %s -> HTTP %s", method, path, resp.status_code)

        if resp.status_code >= 500:
            raise MailWizzTransientError(
                f"MailWizz server error: HTTP {resp.status_code}",
                status_code=resp.status_code,
            )

        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if resp.status_code >= 400:
            # MailWizz returns {"status": "error", "error": "..."} – the error
            # field may be a string or a dict of field errors.
            err = payload.get("error") or payload.get("message") or ""
            err_text = str(err)[:200]
            if resp.status_code == 409 or "already" in err_text.lower():
                raise MailWizzAlreadySubscribedError(
                    "Subscriber already exists", status_code=resp.status_code
                )
            if resp.status_code == 404:
                raise MailWizzError("Not found", status_code=404)
            raise MailWizzError(
                f"MailWizz API error (HTTP {resp.status_code}): {err_text}",
                status_code=resp.status_code,
            )

        return payload

    # ── API operations ───────────────────────────────────────────────────────

    def search_subscriber(self, list_uid: str, email: str) -> Optional[dict]:
        """
        Search a subscriber by email. Returns the subscriber record
        (containing at least ``subscriber_uid`` and ``status``) or None
        if the email is not in the list.
        """
        try:
            payload = self._request(
                "GET",
                f"lists/{list_uid}/subscribers/search-by-email",
                params={"EMAIL": email},
            )
        except MailWizzError as e:
            if e.status_code == 404:
                return None
            raise
        data = payload.get("data") or {}
        record = data.get("record") or data
        if not record or not record.get("subscriber_uid"):
            return None
        return record

    def create_subscriber(self, list_uid: str, fields: dict) -> dict:
        """
        Create a subscriber. ``fields`` must contain at least ``EMAIL``;
        other keys are MailWizz custom field tags (FNAME, LNAME, ...).
        With double opt-in enabled on the list, MailWizz sends the
        confirmation email itself – the plugin never forces a confirmed
        status.
        """
        payload = self._request(
            "POST", f"lists/{list_uid}/subscribers", data=fields
        )
        data = payload.get("data") or {}
        record = data.get("record") or data
        if self.debug:
            logger.debug(
                "MailWizz subscriber created for %s (list %s)",
                mask_email(fields.get("EMAIL", "")),
                list_uid,
            )
        return record

    def test_connection(self, list_uid: str) -> tuple[bool, str]:
        """
        Verify URL, API key and list UID by fetching the list metadata.
        Returns (ok, human-readable message). Never raises.
        """
        try:
            payload = self._request("GET", f"lists/{list_uid}")
        except MailWizzError as e:
            return False, str(e)
        data = payload.get("data") or {}
        record = data.get("record") or {}
        general = record.get("general") or {}
        name = general.get("name") or list_uid
        return True, f"OK – list found: {name}"
