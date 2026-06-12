import json
from datetime import timedelta

import pytest
from django.utils import timezone
from django_scopes import scopes_disabled

from pretix_mailwizz.config import OPTIN_FIELD_NAME

# Dummy credentials for tests only – no real secrets.
TEST_API_URL = "https://newsletter.example.org/api"
TEST_API_KEY = "dummy-test-api-key-not-real"
TEST_LIST_UID = "ab123cd456"


@pytest.fixture
def organizer(db):
    from pretix.base.models import Organizer

    with scopes_disabled():
        # Hybrid-level plugin: must be enabled on organizer level, too.
        return Organizer.objects.create(
            name="Test Org", slug="testorg", plugins="pretix_mailwizz"
        )


@pytest.fixture
def event(organizer):
    from pretix.base.models import Event

    with scopes_disabled():
        ev = Event.objects.create(
            organizer=organizer,
            name="Test Conference",
            slug="conf",
            date_from=timezone.now() + timedelta(days=30),
            plugins="pretix_mailwizz",
            live=True,
            currency="EUR",
        )
    ev.settings.set("mailwizz_api_url", TEST_API_URL)
    ev.settings.set("mailwizz_api_key", TEST_API_KEY)
    ev.settings.set("mailwizz_list_uid", TEST_LIST_UID)
    return ev


def make_order(event, email="maria@example.org", consent=True, locale="de"):
    from pretix.base.models import Order

    meta = {"contact_form_data": {OPTIN_FIELD_NAME: consent}}
    with scopes_disabled():
        return Order.objects.create(
            event=event,
            status=Order.STATUS_PENDING,
            email=email,
            datetime=timezone.now(),
            expires=timezone.now() + timedelta(days=14),
            total=0,
            locale=locale,
            sales_channel=event.organizer.sales_channels.get(identifier="web"),
            meta_info=json.dumps(meta),
        )


@pytest.fixture
def order(event):
    return make_order(event, consent=True)


@pytest.fixture
def order_without_consent(event):
    return make_order(event, consent=False)
