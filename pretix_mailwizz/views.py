from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views import View
from django.views.generic import FormView
from pretix.control.permissions import (
    EventPermissionRequiredMixin,
    OrganizerPermissionRequiredMixin,
)
from pretix.control.views.event import EventSettingsViewMixin
from pretix.control.views.organizer import OrganizerDetailViewMixin

from .config import K_LIST_UID, is_configured, mask_email
from .forms import MailWizzSettingsForm
from .mailwizz import MailWizzClient
from .models import NewsletterSyncLog


class OrganizerSettingsView(
    OrganizerDetailViewMixin,
    OrganizerPermissionRequiredMixin,
    FormView,
):
    template_name = "pretix_mailwizz/organizer_settings.html"
    form_class = MailWizzSettingsForm
    permission = "can_change_organizer_settings"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.organizer
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["organizer"] = self.request.organizer
        return ctx

    def form_valid(self, form):
        form.save(self.request.organizer)
        messages.success(self.request, _("MailWizz settings have been saved."))
        self.request.organizer.log_action(
            "pretix_mailwizz.organizer_settings.changed", user=self.request.user
        )
        return redirect(self.request.path)

    def form_invalid(self, form):
        messages.error(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class EventSettingsView(
    EventSettingsViewMixin,
    EventPermissionRequiredMixin,
    FormView,
):
    template_name = "pretix_mailwizz/event_settings.html"
    form_class = MailWizzSettingsForm
    permission = "can_change_event_settings"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["obj"] = self.request.event
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["event"] = self.request.event
        ctx["configured"] = is_configured(self.request.event)
        logs = NewsletterSyncLog.objects.filter(event=self.request.event)[:20]
        # Mask email addresses even in the backend list view – the full
        # address is visible on the order anyway.
        ctx["sync_logs"] = [
            {
                "order_code": entry.order_code,
                "email_masked": mask_email(entry.email),
                "status": entry.get_status_display(),
                "status_raw": entry.status,
                "attempts": entry.attempts,
                "last_attempt": entry.last_attempt,
                "error_message": entry.error_message,
            }
            for entry in logs
        ]
        return ctx

    def form_valid(self, form):
        form.save(self.request.event)
        messages.success(self.request, _("MailWizz settings have been saved."))
        self.request.event.log_action(
            "pretix_mailwizz.event_settings.changed", user=self.request.user
        )
        return redirect(self.request.path)

    def form_invalid(self, form):
        messages.error(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)


class TestConnectionView(EventPermissionRequiredMixin, View):
    """POST-only: verify URL, API key and list UID against MailWizz."""

    permission = "can_change_event_settings"

    def post(self, request, *args, **kwargs):
        event = request.event
        url = reverse(
            "plugins:pretix_mailwizz:event.settings",
            kwargs={"organizer": request.organizer.slug, "event": event.slug},
        )
        if not is_configured(event):
            messages.error(
                request,
                _("Please save API URL, API key and list UID first."),
            )
            return redirect(url)

        client = MailWizzClient.from_event(event)
        list_uid = (event.settings.get(K_LIST_UID) or "").strip()
        ok, detail = client.test_connection(list_uid)
        if ok:
            messages.success(
                request, _("Connection successful. %(detail)s") % {"detail": detail}
            )
        else:
            messages.error(
                request, _("Connection failed: %(detail)s") % {"detail": detail}
            )
        return redirect(url)
