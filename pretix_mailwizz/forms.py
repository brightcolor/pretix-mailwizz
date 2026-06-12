from django import forms
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea
from i18nfield.strings import LazyI18nString
from pretix.base.forms import SECRET_REDACTED, SecretKeySettingsField

from .config import (
    DEFAULT_CHECKBOX_LABEL,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    K_API_URL,
    K_CHECKBOX_LABEL,
    K_ENABLED,
    K_SHOW_CHECKBOX,
)

BOOL_KEYS_DEFAULT_TRUE = {K_ENABLED, K_SHOW_CHECKBOX}


class MailWizzSettingsForm(forms.Form):
    """
    Settings form used for both organizer-level and event-level settings.
    Field names match hierarkey settings keys, so event settings fall back
    to organizer settings automatically when a key is left unset.
    """

    # ── General ──────────────────────────────────────────────────────────────
    mailwizz_enabled = forms.BooleanField(
        label=_("Enable MailWizz newsletter integration"),
        required=False,
        initial=True,
    )
    mailwizz_show_checkbox = forms.BooleanField(
        label=_("Show newsletter checkbox in checkout"),
        required=False,
        initial=True,
    )
    mailwizz_checkbox_label = I18nFormField(
        label=_("Consent text (checkbox label)"),
        help_text=_(
            "Shown next to the checkbox. The exact text active at the time "
            "of the order is stored with the sync record for accountability. "
            "Leave empty for the built-in default."
        ),
        required=False,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": 3}},
    )
    mailwizz_checkbox_help = I18nFormField(
        label=_("Additional help text below the checkbox (optional)"),
        required=False,
        widget=I18nTextarea,
        widget_kwargs={"attrs": {"rows": 2}},
    )

    # ── MailWizz connection ─────────────────────────────────────────────────
    mailwizz_api_url = forms.URLField(
        label=_("MailWizz API base URL"),
        help_text=_("e.g. https://newsletter.example.org/api"),
        required=False,
    )
    mailwizz_api_key = SecretKeySettingsField(
        label=_("MailWizz API key"),
        required=False,
        help_text=_("Stored value is never displayed again after saving."),
    )
    mailwizz_list_uid = forms.CharField(
        label=_("MailWizz list UID"),
        required=False,
        max_length=64,
        help_text=_(
            "The list must have double opt-in enabled in MailWizz; the plugin "
            "never bypasses the confirmation email."
        ),
    )

    # ── Custom field mapping ─────────────────────────────────────────────────
    mailwizz_field_fname = forms.CharField(
        label=_("Field tag for first name"),
        required=False,
        max_length=64,
        initial="FNAME",
        help_text=_("Leave empty to not transmit the first name."),
    )
    mailwizz_field_lname = forms.CharField(
        label=_("Field tag for last name"),
        required=False,
        max_length=64,
        initial="LNAME",
        help_text=_("Leave empty to not transmit the last name."),
    )
    mailwizz_field_event = forms.CharField(
        label=_("Field tag for event name (optional)"),
        required=False,
        max_length=64,
    )
    mailwizz_field_ordercode = forms.CharField(
        label=_("Field tag for pretix order code (optional)"),
        required=False,
        max_length=64,
    )

    # ── Advanced ─────────────────────────────────────────────────────────────
    mailwizz_timeout = forms.IntegerField(
        label=_("API timeout (seconds)"),
        required=False,
        min_value=1,
        max_value=120,
        initial=DEFAULT_TIMEOUT,
    )
    mailwizz_max_retries = forms.IntegerField(
        label=_("Retries on temporary errors"),
        required=False,
        min_value=0,
        max_value=10,
        initial=DEFAULT_MAX_RETRIES,
    )
    mailwizz_reactivate_unsubscribed = forms.BooleanField(
        label=_("Re-subscribe contacts that have unsubscribed"),
        help_text=_(
            "Not recommended. By default, contacts who unsubscribed in "
            "MailWizz are never re-added by this plugin."
        ),
        required=False,
        initial=False,
    )
    mailwizz_debug_logging = forms.BooleanField(
        label=_("Enable debug logging"),
        help_text=_(
            "Logs API calls (method, path, status code). Email addresses are "
            "masked; the API key and response bodies are never logged."
        ),
        required=False,
        initial=False,
    )

    def __init__(self, *args, obj=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.obj = obj  # Organizer or Event instance
        if obj is None:
            return
        s = obj.settings
        for name, field in self.fields.items():
            if isinstance(field, SecretKeySettingsField):
                if s.get(name):
                    self.initial[name] = SECRET_REDACTED
            elif isinstance(field, forms.BooleanField):
                self.initial[name] = s.get(
                    name, as_type=bool, default=name in BOOL_KEYS_DEFAULT_TRUE
                )
            elif isinstance(field, I18nFormField):
                val = s.get(name, as_type=LazyI18nString)
                if val:
                    self.initial[name] = val
            elif isinstance(field, forms.IntegerField):
                val = s.get(name, as_type=int)
                if val is not None:
                    self.initial[name] = val
            else:
                val = s.get(name)
                if val is not None:
                    self.initial[name] = val
        if not self.initial.get(K_CHECKBOX_LABEL):
            # Show the default text so admins know what customers will see.
            self.fields[K_CHECKBOX_LABEL].widget.attrs["placeholder"] = str(
                DEFAULT_CHECKBOX_LABEL
            )

    def clean_mailwizz_api_url(self):
        val = (self.cleaned_data.get(K_API_URL) or "").strip()
        return val.rstrip("/")

    def save(self, obj) -> None:
        s = obj.settings
        for name, value in self.cleaned_data.items():
            field = self.fields[name]
            if isinstance(field, SecretKeySettingsField):
                if value == SECRET_REDACTED:
                    continue  # unchanged – keep the stored secret
                if value:
                    s.set(name, value)
                else:
                    s.delete(name)
            elif isinstance(field, forms.BooleanField):
                s.set(name, bool(value))
            elif value is None or value == "" or (
                isinstance(value, LazyI18nString) and not str(value).strip()
            ):
                s.delete(name)
            else:
                s.set(name, value)
