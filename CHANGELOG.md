# Changelog

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
