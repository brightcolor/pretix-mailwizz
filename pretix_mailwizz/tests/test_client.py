"""
Tests for the MailWizz API client. All HTTP traffic is faked via an
injected session object – no real requests are made.
"""
import logging
from unittest.mock import MagicMock

import pytest
import requests

from pretix_mailwizz.config import mask_email
from pretix_mailwizz.mailwizz import (
    MailWizzAlreadySubscribedError,
    MailWizzClient,
    MailWizzError,
    MailWizzTransientError,
)

API_URL = "https://newsletter.example.org/api"
API_KEY = "dummy-test-api-key-not-real"
LIST_UID = "ab123cd456"


def fake_response(status_code=200, payload=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload if payload is not None else {}
    return resp


def make_client(responses):
    """Client with a fake session returning the given responses in order."""
    session = MagicMock()
    session.request.side_effect = responses
    return MailWizzClient(API_URL, API_KEY, timeout=5, session=session), session


def test_create_subscriber_sends_correct_payload():
    client, session = make_client([
        fake_response(200, {
            "status": "success",
            "data": {"record": {"subscriber_uid": "sub123", "status": "unconfirmed"}},
        }),
    ])
    record = client.create_subscriber(LIST_UID, {
        "EMAIL": "maria@example.org",
        "FNAME": "Maria",
        "LNAME": "Muster",
    })

    assert record["subscriber_uid"] == "sub123"
    args, kwargs = session.request.call_args
    assert args[0] == "POST"
    assert args[1] == f"{API_URL}/lists/{LIST_UID}/subscribers"
    assert kwargs["data"] == {
        "EMAIL": "maria@example.org",
        "FNAME": "Maria",
        "LNAME": "Muster",
    }
    assert kwargs["headers"]["X-Api-Key"] == API_KEY
    assert kwargs["timeout"] == 5


def test_search_subscriber_found():
    client, session = make_client([
        fake_response(200, {
            "status": "success",
            "data": {"record": {"subscriber_uid": "sub42", "status": "confirmed"}},
        }),
    ])
    record = client.search_subscriber(LIST_UID, "maria@example.org")
    assert record["status"] == "confirmed"
    args, kwargs = session.request.call_args
    assert args[0] == "GET"
    assert "search-by-email" in args[1]
    assert kwargs["params"] == {"EMAIL": "maria@example.org"}


def test_search_subscriber_not_found_returns_none():
    client, _ = make_client([
        fake_response(404, {"status": "error", "error": "not found"}),
    ])
    assert client.search_subscriber(LIST_UID, "nobody@example.org") is None


def test_already_subscribed_raises_specific_error():
    client, _ = make_client([
        fake_response(409, {
            "status": "error",
            "error": "The email address is already registered in the list.",
        }),
    ])
    with pytest.raises(MailWizzAlreadySubscribedError):
        client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})


def test_server_error_is_transient():
    client, _ = make_client([fake_response(502)])
    with pytest.raises(MailWizzTransientError):
        client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})


def test_network_error_is_transient():
    session = MagicMock()
    session.request.side_effect = requests.ConnectionError("refused")
    client = MailWizzClient(API_URL, API_KEY, session=session)
    with pytest.raises(MailWizzTransientError):
        client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})


def test_client_error_is_permanent():
    client, _ = make_client([
        fake_response(400, {"status": "error", "error": "invalid email"}),
    ])
    with pytest.raises(MailWizzError) as excinfo:
        client.create_subscriber(LIST_UID, {"EMAIL": "broken"})
    assert not isinstance(excinfo.value, MailWizzTransientError)


def test_test_connection_ok():
    client, _ = make_client([
        fake_response(200, {
            "status": "success",
            "data": {"record": {"general": {"name": "My Newsletter"}}},
        }),
    ])
    ok, msg = client.test_connection(LIST_UID)
    assert ok
    assert "My Newsletter" in msg


def test_test_connection_failure_does_not_raise():
    client, _ = make_client([
        fake_response(401, {"status": "error", "error": "unauthorized"}),
    ])
    ok, msg = client.test_connection(LIST_UID)
    assert not ok
    assert "unauthorized" in msg


def test_api_key_never_logged(caplog):
    """Even with debug logging on a failing request, the key must not leak."""
    caplog.set_level(logging.DEBUG)
    session = MagicMock()
    session.request.side_effect = [
        fake_response(200, {"data": {"record": {"subscriber_uid": "s1"}}}),
        fake_response(500),
        requests.Timeout("timed out"),
    ]
    client = MailWizzClient(API_URL, API_KEY, debug=True, session=session)

    client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})
    with pytest.raises(MailWizzTransientError):
        client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})
    with pytest.raises(MailWizzTransientError):
        client.create_subscriber(LIST_UID, {"EMAIL": "maria@example.org"})

    assert API_KEY not in caplog.text
    # Full email addresses are masked in logs, too.
    assert "maria@example.org" not in caplog.text


def test_mask_email():
    assert mask_email("maria@example.org") == "m***@example.org"
    assert mask_email("") == "***"
    assert mask_email("no-at-sign") == "***"
