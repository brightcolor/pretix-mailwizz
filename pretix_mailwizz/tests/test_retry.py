"""
Integration tests for the manual retry of failed newsletter syncs.

Exercises the full control-panel path (authenticated request -> view ->
re-queued task) with all HTTP traffic to MailWizz faked.
"""
from unittest.mock import MagicMock

import pytest
from django.urls import reverse
from django_scopes import scopes_disabled

from pretix_mailwizz.models import NewsletterSyncLog
from pretix_mailwizz.tests.conftest import TEST_LIST_UID


def _fake_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


def _success_session(self, method, url, **kwargs):
    """
    Drop-in for ``requests.Session.request`` (patched on the class, so the
    session instance arrives as ``self``): search -> not found, create -> ok.
    """
    if method == "GET" and "search-by-email" in url:
        return _fake_response(404, {"status": "error"})
    if method == "POST":
        return _fake_response(200, {
            "status": "success",
            "data": {"record": {"subscriber_uid": "sub-retry", "status": "unconfirmed"}},
        })
    return _fake_response(200, {})


@pytest.fixture
def admin_client(client, event):
    from pretix.base.models import Team, User

    with scopes_disabled():
        user = User.objects.create_user("admin@example.org", "dummy-pw-not-real")
        team = Team.objects.create(
            organizer=event.organizer,
            all_events=True,
            all_event_permissions=True,
        )
        team.members.add(user)
    client.force_login(user)
    return client


@pytest.fixture
def failed_log(event):
    with scopes_disabled():
        return NewsletterSyncLog.objects.create(
            event=event,
            organizer=event.organizer,
            order_code="ABCDE",
            email="maria@example.org",
            list_uid=TEST_LIST_UID,
            status=NewsletterSyncLog.STATUS_FAILED,
            error_message="MailWizz unreachable: ConnectionError",
            attempts=3,
        )


def _retry_url(event):
    return reverse(
        "plugins:pretix_mailwizz:event.retry",
        kwargs={"organizer": event.organizer.slug, "event": event.slug},
    )


def test_retry_single_failed_sync_succeeds(admin_client, event, failed_log, monkeypatch):
    monkeypatch.setattr("requests.Session.request", _success_session)

    resp = admin_client.post(_retry_url(event), {"pk": failed_log.pk})
    assert resp.status_code == 302  # redirect back to settings

    with scopes_disabled():
        failed_log.refresh_from_db()
    # Eager celery: the task ran inline and the sync now succeeded.
    assert failed_log.status == NewsletterSyncLog.STATUS_SUCCESS
    assert failed_log.subscriber_uid == "sub-retry"
    assert failed_log.error_message == "Subscriber already exists" or failed_log.error_message == ""


def test_retry_all_failed(admin_client, event, monkeypatch):
    monkeypatch.setattr("requests.Session.request", _success_session)
    with scopes_disabled():
        for code in ("AAA11", "BBB22"):
            NewsletterSyncLog.objects.create(
                event=event, organizer=event.organizer, order_code=code,
                email=f"{code}@example.org", list_uid=TEST_LIST_UID,
                status=NewsletterSyncLog.STATUS_FAILED, attempts=1,
            )

    resp = admin_client.post(_retry_url(event))
    assert resp.status_code == 302

    with scopes_disabled():
        statuses = set(
            NewsletterSyncLog.objects.filter(event=event).values_list("status", flat=True)
        )
    assert statuses == {NewsletterSyncLog.STATUS_SUCCESS}


def test_retry_does_not_touch_success_or_skipped(admin_client, event, monkeypatch):
    monkeypatch.setattr("requests.Session.request", _success_session)
    with scopes_disabled():
        ok = NewsletterSyncLog.objects.create(
            event=event, organizer=event.organizer, order_code="OK001",
            email="ok@example.org", list_uid=TEST_LIST_UID,
            status=NewsletterSyncLog.STATUS_SUCCESS, subscriber_uid="keep-me", attempts=1,
        )
        skip = NewsletterSyncLog.objects.create(
            event=event, organizer=event.organizer, order_code="SK001",
            email="skip@example.org", list_uid=TEST_LIST_UID,
            status=NewsletterSyncLog.STATUS_SKIPPED, attempts=1,
        )

    resp = admin_client.post(_retry_url(event))
    assert resp.status_code == 302

    with scopes_disabled():
        ok.refresh_from_db()
        skip.refresh_from_db()
    # Untouched: a "retry all failed" must never re-process these.
    assert ok.status == NewsletterSyncLog.STATUS_SUCCESS
    assert ok.subscriber_uid == "keep-me"
    assert ok.attempts == 1
    assert skip.status == NewsletterSyncLog.STATUS_SKIPPED


def test_retry_requires_permission(client, event, failed_log):
    from pretix.base.models import User

    with scopes_disabled():
        user = User.objects.create_user("noperm@example.org", "dummy-pw-not-real")
    client.force_login(user)

    resp = client.post(_retry_url(event), {"pk": failed_log.pk})
    assert resp.status_code in (403, 404)
    with scopes_disabled():
        failed_log.refresh_from_db()
    assert failed_log.status == NewsletterSyncLog.STATUS_FAILED  # unchanged
