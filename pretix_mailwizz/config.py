"""
Settings keys, defaults and small helpers shared across the plugin.

All values are stored via pretix's hierarchical settings (hierarkey), so
event settings automatically fall back to organizer-level settings if a
key is not set on the event itself.
"""
from i18nfield.strings import LazyI18nString

# Name of the checkout form field. This key also ends up in
# order.meta_info['contact_form_data'].
OPTIN_FIELD_NAME = "pretix_mailwizz_newsletter_optin"

# Key under which the consent record is stored in order.meta_info.
META_INFO_KEY = "pretix_mailwizz"

# ── Settings keys (hierarkey: event → organizer fallback) ────────────────────
K_ENABLED = "mailwizz_enabled"
K_SHOW_CHECKBOX = "mailwizz_show_checkbox"
K_CHECKBOX_LABEL = "mailwizz_checkbox_label"
K_CHECKBOX_HELP = "mailwizz_checkbox_help"
K_API_URL = "mailwizz_api_url"
K_API_KEY = "mailwizz_api_key"
K_LIST_UID = "mailwizz_list_uid"
K_FIELD_FNAME = "mailwizz_field_fname"
K_FIELD_LNAME = "mailwizz_field_lname"
K_FIELD_EVENT = "mailwizz_field_event"
K_FIELD_ORDERCODE = "mailwizz_field_ordercode"
K_TIMEOUT = "mailwizz_timeout"
K_MAX_RETRIES = "mailwizz_max_retries"
K_DEBUG = "mailwizz_debug_logging"
K_REACTIVATE = "mailwizz_reactivate_unsubscribed"

DEFAULT_TIMEOUT = 10
DEFAULT_MAX_RETRIES = 3

DEFAULT_CHECKBOX_LABEL = LazyI18nString({
    "en": (
        "I would like to subscribe to the newsletter and be informed about "
        "news, events and offers. I can unsubscribe at any time."
    ),
    "de": (
        "Ich möchte den Newsletter abonnieren und über Neuigkeiten, Events "
        "und Angebote informiert werden. Ich kann mich jederzeit wieder "
        "abmelden."
    ),
})


def get_bool(settings, key: str, default: bool = False) -> bool:
    return settings.get(key, as_type=bool, default=default)


def get_int(settings, key: str, default: int) -> int:
    try:
        val = settings.get(key, as_type=int, default=default)
        return val if val is not None else default
    except (TypeError, ValueError):
        return default


def get_label(settings) -> LazyI18nString:
    """Return the configured consent label, or the built-in default."""
    val = settings.get(K_CHECKBOX_LABEL, as_type=LazyI18nString)
    if val and str(val).strip():
        return val
    return DEFAULT_CHECKBOX_LABEL


def is_enabled(event) -> bool:
    """Master switch: plugin enabled for this event (with organizer fallback)."""
    return get_bool(event.settings, K_ENABLED, default=True)


def show_checkbox(event) -> bool:
    return get_bool(event.settings, K_SHOW_CHECKBOX, default=True)


def is_configured(event) -> bool:
    """True if API URL, API key and list UID are all present."""
    s = event.settings
    return bool(
        (s.get(K_API_URL) or "").strip()
        and (s.get(K_API_KEY) or "").strip()
        and (s.get(K_LIST_UID) or "").strip()
    )


def mask_email(email: str) -> str:
    """Mask an email address for data-minimal logging: m***@example.org"""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"
