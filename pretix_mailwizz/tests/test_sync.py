"""
Tests for the sync logic in tasks.py (idempotency, existing subscribers,
unsubscribed handling, payload building).
"""
from unittest.mock import MagicMock

import pytest

from pretix_mailwizz.mailwizz import (
    MailWizzAlreadySubscribedError,
    MailWizzClient,
    MailWizzTransientError,
)
from pretix_mailwizz.models import NewsletterSyncLog
from pretix_mailwizz.signals import handle_order_placed
from pretix_mailwizz.tasks import build_subscriber_payload, sync_log_entry

from .conftest import TEST_LIST_UID


def make_log(event, order, **kwargs):
    defaults = dict(
        organizer=event.organizer,
        event=event,
        order_code=order.code,
        email=order.email,
        list_uid=TEST_LIST_UID,
        status=NewsletterSyncLog.STATUS_PENDING,
    )
    defaults.update(kwargs)
    return NewsletterSyncLog.objects.create(**defaults)


def mock_client(search_result=None, create_result=None, create_error=None):
    client = MagicMock(spec=MailWizzClient)
    client.search_subscriber.return_value = search_result
    if create_error:
        client.create_subscriber.side_effect = create_error
    else:
        client.create_subscriber.return_value = create_result or {
            "subscriber_uid": "new-sub-1", "status": "unconfirmed",
        }
    return client


@pytest.mark.django_db
def test_successful_sync(event, order):
    log = make_log(event, order)
    client = mock_client()
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SUCCESS
    assert log.subscriber_uid == "new-sub-1"
    assert log.attempts == 1
    assert log.last_attempt is not None
    client.create_subscriber.assert_called_once()
    payload = client.create_subscriber.call_args[0][1]
    assert payload["EMAIL"] == order.email


@pytest.mark.django_db
def test_already_success_is_not_sent_again(event, order):
    log = make_log(event, order, status=NewsletterSyncLog.STATUS_SUCCESS)
    client = mock_client()
    sync_log_entry(log, client=client)
    client.search_subscriber.assert_not_called()
    client.create_subscriber.assert_not_called()


@pytest.mark.django_db
def test_existing_confirmed_subscriber_treated_as_success(event, order):
    log = make_log(event, order)
    client = mock_client(search_result={"subscriber_uid": "old-1", "status": "confirmed"})
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SUCCESS
    assert log.subscriber_uid == "old-1"
    assert "already" in log.error_message.lower()
    client.create_subscriber.assert_not_called()


@pytest.mark.django_db
def test_unsubscribed_subscriber_not_reactivated_by_default(event, order):
    log = make_log(event, order)
    client = mock_client(
        search_result={"subscriber_uid": "old-2", "status": "unsubscribed"}
    )
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SKIPPED
    client.create_subscriber.assert_not_called()


@pytest.mark.django_db
def test_unsubscribed_subscriber_reactivated_if_configured(event, order):
    event.settings.set("mailwizz_reactivate_unsubscribed", True)
    log = make_log(event, order)
    client = mock_client(
        search_result={"subscriber_uid": "old-2", "status": "unsubscribed"}
    )
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SUCCESS
    client.create_subscriber.assert_called_once()


@pytest.mark.django_db
def test_already_exists_on_create_treated_as_success(event, order):
    log = make_log(event, order)
    client = mock_client(create_error=MailWizzAlreadySubscribedError("exists"))
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SUCCESS


@pytest.mark.django_db
def test_transient_error_marks_failed_and_reraises(event, order):
    log = make_log(event, order)
    client = mock_client(create_error=MailWizzTransientError("HTTP 503"))
    with pytest.raises(MailWizzTransientError):
        sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_FAILED
    assert log.attempts == 1
    # failed entries may be retried
    client2 = mock_client()
    sync_log_entry(log, client=client2)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_SUCCESS
    assert log.attempts == 2


@pytest.mark.django_db
def test_unconfigured_event_marks_failed_without_api_call(event, order):
    event.settings.delete("mailwizz_api_key")
    event.organizer.settings.delete("mailwizz_api_key")
    log = make_log(event, order)
    client = mock_client()
    sync_log_entry(log, client=client)
    log.refresh_from_db()
    assert log.status == NewsletterSyncLog.STATUS_FAILED
    assert "not" in log.error_message.lower()
    client.create_subscriber.assert_not_called()


@pytest.mark.django_db
def test_payload_includes_mapped_custom_fields(event, order):
    event.settings.set("mailwizz_field_event", "EVENTNAME")
    event.settings.set("mailwizz_field_ordercode", "ORDERCODE")
    log = make_log(event, order)
    payload = build_subscriber_payload(log, order=order)
    assert payload["EMAIL"] == order.email
    assert payload["EVENTNAME"] == str(event.name)
    assert payload["ORDERCODE"] == order.code
    # No invoice address on this order – no name fields transmitted
    assert "FNAME" not in payload
    assert "LNAME" not in payload


@pytest.mark.django_db
def test_payload_includes_names_from_invoice_address(event, order):
    from django_scopes import scopes_disabled
    from pretix.base.models import InvoiceAddress

    event.settings.set("mailwizz_field_fname", "FNAME")
    event.settings.set("mailwizz_field_lname", "LNAME")
    with scopes_disabled():
        InvoiceAddress.objects.create(
            order=order,
            name_parts={
                "_scheme": "given_family",
                "given_name": "Maria",
                "family_name": "Muster",
            },
        )
    order.refresh_from_db()
    log = make_log(event, order)
    payload = build_subscriber_payload(log, order=order)
    assert payload["FNAME"] == "Maria"
    assert payload["LNAME"] == "Muster"


@pytest.mark.django_db
def test_full_flow_consent_to_success(event, order):
    """order_placed handler + sync produce exactly one successful record."""
    handle_order_placed(event, order)
    log = NewsletterSyncLog.objects.get()
    client = mock_client()
    sync_log_entry(log, client=client)
    # Running the whole flow again must not trigger another API call.
    handle_order_placed(event, order)
    assert NewsletterSyncLog.objects.count() == 1
    log.refresh_from_db()
    client2 = mock_client()
    sync_log_entry(log, client=client2)
    client2.create_subscriber.assert_not_called()
