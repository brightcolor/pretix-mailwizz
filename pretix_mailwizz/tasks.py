"""
Asynchronous synchronisation of newsletter opt-ins to MailWizz.

The actual work lives in :func:`sync_log_entry` so it can be unit-tested
and reused without celery; :func:`mailwizz_sync_task` is the thin celery
wrapper with retry handling that is enqueued after the order transaction
commits.
"""
import logging

from django.utils import timezone
from django_scopes import scope, scopes_disabled
from pretix.celery_app import app

from .config import (
    DEFAULT_MAX_RETRIES,
    K_FIELD_EVENT,
    K_FIELD_FNAME,
    K_FIELD_LNAME,
    K_FIELD_ORDERCODE,
    K_MAX_RETRIES,
    K_REACTIVATE,
    get_bool,
    get_int,
    is_configured,
    mask_email,
)
from .mailwizz import (
    STATUS_CONFIRMED,
    STATUS_UNCONFIRMED,
    STATUS_UNSUBSCRIBED,
    MailWizzAlreadySubscribedError,
    MailWizzClient,
    MailWizzError,
    MailWizzTransientError,
)
from .models import NewsletterSyncLog

logger = logging.getLogger(__name__)


def build_subscriber_payload(log: NewsletterSyncLog, order=None) -> dict:
    """
    Assemble the MailWizz field payload from the sync log, the order's
    invoice address (if any) and the configured custom field mappings.
    """
    event = log.event
    s = event.settings
    payload = {"EMAIL": log.email}

    fname = lname = ""
    if order is not None:
        try:
            parts = order.invoice_address.name_parts or {}
            fname = parts.get("given_name", "") or ""
            lname = parts.get("family_name", "") or ""
            if not (fname or lname):
                full = (order.invoice_address.name or "").strip()
                if full:
                    chunks = full.split(" ", 1)
                    fname = chunks[0]
                    lname = chunks[1] if len(chunks) > 1 else ""
        except Exception:
            pass  # no invoice address – names are optional

    tag_fname = (s.get(K_FIELD_FNAME) or "").strip()
    tag_lname = (s.get(K_FIELD_LNAME) or "").strip()
    tag_event = (s.get(K_FIELD_EVENT) or "").strip()
    tag_ordercode = (s.get(K_FIELD_ORDERCODE) or "").strip()

    if tag_fname and fname:
        payload[tag_fname] = fname
    if tag_lname and lname:
        payload[tag_lname] = lname
    if tag_event:
        payload[tag_event] = str(event.name)
    if tag_ordercode:
        payload[tag_ordercode] = log.order_code
    return payload


def sync_log_entry(log: NewsletterSyncLog, client: MailWizzClient = None) -> None:
    """
    Process one sync log entry. Idempotent: entries already in ``success``
    or ``skipped`` state are never sent again.

    Raises :class:`MailWizzTransientError` so the celery wrapper can retry;
    permanent errors are recorded on the log entry instead.
    """
    if log.status in (NewsletterSyncLog.STATUS_SUCCESS, NewsletterSyncLog.STATUS_SKIPPED):
        return

    event = log.event
    masked = mask_email(log.email)

    if not is_configured(event):
        log.status = NewsletterSyncLog.STATUS_FAILED
        log.error_message = "MailWizz is not fully configured (URL, API key, list UID)"
        log.save(update_fields=["status", "error_message", "updated"])
        logger.warning(
            "MailWizz sync for order %s skipped: plugin not configured", log.order_code
        )
        return

    client = client or MailWizzClient.from_event(event)
    log.attempts += 1
    log.last_attempt = timezone.now()

    try:
        # Check for an existing subscriber first so we never reactivate
        # unsubscribed contacts and treat existing ones gracefully.
        existing = client.search_subscriber(log.list_uid, log.email)
        if existing:
            status = (existing.get("status") or "").lower()
            if status == STATUS_UNSUBSCRIBED and not get_bool(
                event.settings, K_REACTIVATE, default=False
            ):
                log.status = NewsletterSyncLog.STATUS_SKIPPED
                log.error_message = "Subscriber has unsubscribed – not reactivated"
                log.subscriber_uid = existing.get("subscriber_uid", "")
                log.save()
                logger.info(
                    "MailWizz: %s is unsubscribed, not reactivating (order %s)",
                    masked, log.order_code,
                )
                return
            if status in (STATUS_CONFIRMED, STATUS_UNCONFIRMED):
                log.status = NewsletterSyncLog.STATUS_SUCCESS
                log.error_message = "Subscriber already exists"
                log.subscriber_uid = existing.get("subscriber_uid", "")
                log.save()
                logger.info(
                    "MailWizz: %s already subscribed (order %s)", masked, log.order_code
                )
                return
            # Any other status (e.g. blacklisted): fall through and let the
            # create call decide; MailWizz will reject it if not allowed.

        order = None
        try:
            with scopes_disabled():
                order = log.event.orders.get(code=log.order_code)
        except Exception:
            pass

        record = client.create_subscriber(
            log.list_uid, build_subscriber_payload(log, order=order)
        )
        log.status = NewsletterSyncLog.STATUS_SUCCESS
        log.error_message = ""
        log.subscriber_uid = (record or {}).get("subscriber_uid", "") or ""
        log.save()
        logger.info(
            "MailWizz: subscribed %s to list %s (order %s)",
            masked, log.list_uid, log.order_code,
        )

    except MailWizzAlreadySubscribedError:
        log.status = NewsletterSyncLog.STATUS_SUCCESS
        log.error_message = "Subscriber already exists"
        log.save()
        logger.info("MailWizz: %s already exists (order %s)", masked, log.order_code)

    except MailWizzTransientError as e:
        log.status = NewsletterSyncLog.STATUS_FAILED
        log.error_message = str(e)[:255]
        log.save()
        raise  # let the celery wrapper retry

    except MailWizzError as e:
        log.status = NewsletterSyncLog.STATUS_FAILED
        log.error_message = str(e)[:255]
        log.save()
        logger.warning(
            "MailWizz sync failed permanently for order %s: %s",
            log.order_code, log.error_message,
        )


@app.task(bind=True, name="pretix_mailwizz.sync_subscriber", acks_late=True)
def mailwizz_sync_task(self, log_pk: int) -> None:
    with scopes_disabled():
        log = (
            NewsletterSyncLog.objects.select_related("event", "organizer")
            .filter(pk=log_pk)
            .first()
        )
    if log is None:
        return

    with scope(organizer=log.organizer):
        try:
            sync_log_entry(log)
        except MailWizzTransientError as e:
            max_retries = get_int(log.event.settings, K_MAX_RETRIES, DEFAULT_MAX_RETRIES)
            if self.request.retries >= max_retries:
                logger.warning(
                    "MailWizz sync for order %s gave up after %d attempts: %s",
                    log.order_code, log.attempts, str(e)[:200],
                )
                return
            # Exponential backoff: 1 min, 2 min, 4 min, ...
            raise self.retry(countdown=60 * (2 ** self.request.retries), exc=e)
