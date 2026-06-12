# Changelog

## 1.1.0 (2026-06-12)

* Manual retry for failed syncs: the event settings page now shows a
  "Retry" button per failed entry and a "Retry all failed" button. Failed
  entries are reset to pending and re-queued; successful or skipped
  entries are never touched (`event.retry` view).
* Migration `0001` now pins to a stable long-standing pretixbase
  migration (instead of a release-specific latest one) so a fresh install
  applies cleanly across supported pretix versions.
* The MailWizz menu item under event settings is only shown to users with
  the `can_change_event_settings` permission.

## 1.0.0 (2026-06-11)

* Initial release.
* Optional, never pre-selected newsletter opt-in checkbox in the checkout
  contact form (`contact_form_fields`).
* Consent documentation (timestamp, consent text, locale, list UID) in
  `order.meta_info` and in a separate `NewsletterSyncLog` audit model.
* Asynchronous MailWizz sync via celery task after `order_placed`, with
  exponential backoff on temporary errors; the checkout is never blocked.
* Idempotent processing (unique constraint per event/order/email/list),
  graceful handling of existing subscribers, unsubscribed contacts are
  not reactivated by default.
* Organizer-level default settings with per-event overrides, secret API
  key field, connection test button, sync log overview in the backend.
* Data-minimal logging (masked email addresses, no API keys, no response
  bodies), German and English translations.
