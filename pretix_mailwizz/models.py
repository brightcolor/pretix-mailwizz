from django.db import models
from django.utils.translation import gettext_lazy as _


class NewsletterSyncLog(models.Model):
    """
    Audit/sync record for one newsletter subscription attempt.

    Deliberately kept separate from the order itself so order data and
    newsletter sync data stay cleanly apart. Only data needed to perform
    and document the sync is stored here.
    """

    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("pending")),
        (STATUS_SUCCESS, _("success")),
        (STATUS_FAILED, _("failed")),
        (STATUS_SKIPPED, _("skipped")),
    ]

    organizer = models.ForeignKey(
        "pretixbase.Organizer",
        on_delete=models.CASCADE,
        related_name="mailwizz_sync_logs",
    )
    event = models.ForeignKey(
        "pretixbase.Event",
        on_delete=models.CASCADE,
        related_name="mailwizz_sync_logs",
    )
    order_code = models.CharField(max_length=16)
    email = models.EmailField()
    list_uid = models.CharField(max_length=64)

    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    # Short, data-minimal error summary – never a full API response.
    error_message = models.CharField(max_length=255, blank=True, default="")
    attempts = models.PositiveIntegerField(default=0)
    last_attempt = models.DateTimeField(null=True, blank=True)
    subscriber_uid = models.CharField(max_length=64, blank=True, default="")

    # Consent documentation (GDPR accountability)
    consent_text = models.TextField(blank=True, default="")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    locale = models.CharField(max_length=32, blank=True, default="")

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "order_code", "email", "list_uid"],
                name="pretix_mailwizz_unique_sync",
            ),
        ]
        ordering = ("-created",)

    def __str__(self) -> str:
        return f"{self.order_code} → list {self.list_uid} [{self.status}]"
