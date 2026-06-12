"""
Tests for the checkout checkbox (contact_form_fields signal) and the
consent handling on order placement.
"""
from unittest.mock import MagicMock, patch

import pytest
from django import forms
from pretix.presale.signals import contact_form_fields

from pretix_mailwizz.config import META_INFO_KEY, OPTIN_FIELD_NAME
from pretix_mailwizz.models import NewsletterSyncLog
from pretix_mailwizz.signals import handle_order_placed, on_order_placed

from .conftest import TEST_LIST_UID, make_order


@pytest.mark.django_db
def test_checkbox_shown_when_plugin_active(event):
    responses = contact_form_fields.send(event, request=MagicMock())
    fields = {}
    for _, resp in responses:
        fields.update(resp)
    assert OPTIN_FIELD_NAME in fields
    assert isinstance(fields[OPTIN_FIELD_NAME], forms.BooleanField)


@pytest.mark.django_db
def test_checkbox_not_shown_when_disabled(event):
    event.settings.set("mailwizz_enabled", False)
    responses = contact_form_fields.send(event, request=MagicMock())
    for _, resp in responses:
        assert OPTIN_FIELD_NAME not in resp


@pytest.mark.django_db
def test_checkbox_not_shown_without_configuration(event):
    event.settings.delete("mailwizz_api_key")
    event.organizer.settings.delete("mailwizz_api_key")
    responses = contact_form_fields.send(event, request=MagicMock())
    for _, resp in responses:
        assert OPTIN_FIELD_NAME not in resp


@pytest.mark.django_db
def test_checkbox_not_preselected_and_optional(event):
    responses = contact_form_fields.send(event, request=MagicMock())
    fields = {}
    for _, resp in responses:
        fields.update(resp)
    field = fields[OPTIN_FIELD_NAME]
    assert field.initial is False
    assert field.required is False


@pytest.mark.django_db
def test_no_consent_no_api_and_no_synclog(event, order_without_consent):
    with patch("pretix_mailwizz.mailwizz.MailWizzClient.from_event") as client_factory:
        handle_order_placed(event, order_without_consent)
    client_factory.assert_not_called()
    assert NewsletterSyncLog.objects.count() == 0


@pytest.mark.django_db
def test_consent_is_stored_in_meta_info(event, order):
    handle_order_placed(event, order)
    order.refresh_from_db()
    record = order.meta_info_data[META_INFO_KEY]
    assert record["consent"] is True
    assert record["consent_timestamp"]
    assert record["consent_text"]
    assert record["locale"] == "de"
    assert record["list_uid"] == TEST_LIST_UID
    # German consent text was active for this order's locale
    assert "Newsletter" in record["consent_text"]


@pytest.mark.django_db
def test_synclog_created_on_consent(event, order):
    handle_order_placed(event, order)
    log = NewsletterSyncLog.objects.get()
    assert log.order_code == order.code
    assert log.email == order.email
    assert log.list_uid == TEST_LIST_UID
    assert log.status == NewsletterSyncLog.STATUS_PENDING
    assert log.organizer == event.organizer
    assert log.consent_text
    assert log.consent_timestamp


@pytest.mark.django_db
def test_duplicate_processing_creates_single_synclog(event, order):
    handle_order_placed(event, order)
    handle_order_placed(event, order)
    assert NewsletterSyncLog.objects.count() == 1


@pytest.mark.django_db
def test_order_placed_never_raises(event, order):
    # Even if everything inside explodes, checkout must not be affected.
    with patch(
        "pretix_mailwizz.signals.handle_order_placed",
        side_effect=RuntimeError("boom"),
    ):
        on_order_placed(event, order=order)  # must not raise


@pytest.mark.django_db
def test_enqueue_failure_does_not_raise(event, order, django_capture_on_commit_callbacks):
    with patch(
        "pretix_mailwizz.tasks.mailwizz_sync_task.apply_async",
        side_effect=RuntimeError("broker down"),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            handle_order_placed(event, order)
    # Entry stays pending and can be retried later.
    log = NewsletterSyncLog.objects.get()
    assert log.status == NewsletterSyncLog.STATUS_PENDING


@pytest.mark.django_db
def test_settings_fallback_organizer_to_event(organizer):
    """Event without own values inherits the organizer-level settings."""
    from datetime import timedelta

    from django.utils import timezone
    from django_scopes import scopes_disabled
    from pretix.base.models import Event

    organizer.settings.set("mailwizz_api_url", "https://org-level.example.org/api")
    organizer.settings.set("mailwizz_api_key", "org-level-dummy-key")
    organizer.settings.set("mailwizz_list_uid", "orglist123")

    with scopes_disabled():
        ev = Event.objects.create(
            organizer=organizer,
            name="Second Event",
            slug="second",
            date_from=timezone.now() + timedelta(days=5),
            plugins="pretix_mailwizz",
            currency="EUR",
        )

    from pretix_mailwizz.config import is_configured

    assert ev.settings.get("mailwizz_api_url") == "https://org-level.example.org/api"
    assert ev.settings.get("mailwizz_list_uid") == "orglist123"
    assert is_configured(ev)

    # Event-level value overrides the organizer default
    ev.settings.set("mailwizz_list_uid", "eventlist456")
    assert ev.settings.get("mailwizz_list_uid") == "eventlist456"


@pytest.mark.django_db
def test_consent_synclog_after_full_flow(event):
    """Order with consent → handler → sync log referencing the right order."""
    order = make_order(event, email="kunde@example.org", consent=True)
    handle_order_placed(event, order)
    log = NewsletterSyncLog.objects.get(order_code=order.code)
    assert log.email == "kunde@example.org"
