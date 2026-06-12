import json
import logging
from collections import OrderedDict

from django import forms
from django.db import transaction
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import order_placed
from pretix.control.signals import nav_event_settings, nav_organizer
from pretix.presale.signals import contact_form_fields

from .config import (
    K_CHECKBOX_HELP,
    K_LIST_UID,
    META_INFO_KEY,
    OPTIN_FIELD_NAME,
    get_label,
    is_configured,
    is_enabled,
    show_checkbox,
)
from .models import NewsletterSyncLog

logger = logging.getLogger(__name__)


# ── Checkout: opt-in checkbox ────────────────────────────────────────────────

@receiver(contact_form_fields, dispatch_uid="pretix_mailwizz_contact_form_fields")
def add_newsletter_optin_field(sender, request=None, **kwargs):
    """
    Add the (never pre-selected, never required) newsletter opt-in
    checkbox to the checkout contact form. Its value is stored by pretix
    in order.meta_info['contact_form_data'][OPTIN_FIELD_NAME].
    """
    event = sender
    if not is_enabled(event) or not show_checkbox(event):
        return {}
    if not is_configured(event):
        # Without a working MailWizz configuration the checkbox would
        # collect consent we cannot act on – better not to show it.
        return {}

    help_text = event.settings.get(K_CHECKBOX_HELP) or ""
    field = forms.BooleanField(
        label=str(get_label(event.settings)),
        help_text=str(help_text),
        required=False,
        initial=False,
    )
    return OrderedDict([(OPTIN_FIELD_NAME, field)])


# ── Order placed: record consent + enqueue sync ──────────────────────────────

@receiver(order_placed, dispatch_uid="pretix_mailwizz_order_placed")
def on_order_placed(sender, order=None, **kwargs):
    """
    Never raises: any failure here is logged but must not interfere with
    the order placement.
    """
    try:
        handle_order_placed(sender, order)
    except Exception:
        logger.exception(
            "pretix_mailwizz: error while handling order_placed for order %s",
            getattr(order, "code", "?"),
        )


def handle_order_placed(event, order) -> None:
    if order is None or not is_enabled(event):
        return

    meta_info = order.meta_info_data or {}
    consent = meta_info.get("contact_form_data", {}).get(OPTIN_FIELD_NAME)
    if not consent:
        return  # no active consent – never contact MailWizz

    if not order.email:
        return

    list_uid = (event.settings.get(K_LIST_UID) or "").strip()
    if not is_configured(event) or not list_uid:
        logger.warning(
            "pretix_mailwizz: consent given on order %s but MailWizz is not "
            "configured – nothing sent", order.code,
        )
        return

    consent_text = str(get_label(event.settings).localize(order.locale or "en"))
    now = timezone.now()

    # Document the consent with the order (GDPR accountability).
    meta_info[META_INFO_KEY] = {
        "consent": True,
        "consent_timestamp": now.isoformat(),
        "consent_text": consent_text,
        "locale": order.locale or "",
        "list_uid": list_uid,
    }
    order.meta_info = json.dumps(meta_info)
    order.save(update_fields=["meta_info"])

    # Separate sync/audit record, idempotent via unique constraint.
    log, created = NewsletterSyncLog.objects.get_or_create(
        event=event,
        order_code=order.code,
        email=order.email,
        list_uid=list_uid,
        defaults={
            "organizer": event.organizer,
            "status": NewsletterSyncLog.STATUS_PENDING,
            "consent_text": consent_text,
            "consent_timestamp": now,
            "locale": order.locale or "",
        },
    )
    if not created and log.status in (
        NewsletterSyncLog.STATUS_SUCCESS,
        NewsletterSyncLog.STATUS_SKIPPED,
    ):
        return  # already processed – do not send again

    # Enqueue after commit so the task never sees an uncommitted order.
    from .tasks import mailwizz_sync_task

    def _enqueue():
        try:
            mailwizz_sync_task.apply_async(args=[log.pk])
        except Exception:
            logger.exception(
                "pretix_mailwizz: could not enqueue sync task for order %s "
                "(entry stays 'pending' and can be retried)", log.order_code,
            )

    transaction.on_commit(_enqueue)


# ── Control panel navigation ─────────────────────────────────────────────────

@receiver(nav_organizer, dispatch_uid="pretix_mailwizz_nav_organizer")
def nav_organizer_mailwizz(sender, request=None, organizer=None, **kwargs):
    if not request.user.has_organizer_permission(
        organizer, "can_change_organizer_settings", request
    ):
        return []
    url = reverse(
        "plugins:pretix_mailwizz:organizer.settings",
        kwargs={"organizer": organizer.slug},
    )
    return [
        {
            "label": _("MailWizz Newsletter"),
            "url": url,
            "active": request.path.startswith(url),
            "icon": "envelope",
        }
    ]


@receiver(nav_event_settings, dispatch_uid="pretix_mailwizz_nav_event_settings")
def nav_event_settings_mailwizz(sender, request=None, **kwargs):
    if not request.user.has_event_permission(
        request.organizer, request.event, "can_change_event_settings", request=request
    ):
        return []
    url = reverse(
        "plugins:pretix_mailwizz:event.settings",
        kwargs={"organizer": request.organizer.slug, "event": request.event.slug},
    )
    return [
        {
            "label": _("MailWizz Newsletter"),
            "url": url,
            "active": request.path.startswith(url),
        }
    ]
