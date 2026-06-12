from django.utils.translation import gettext_lazy as _

try:
    from pretix.base.plugins import PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID, PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2025.10 or above to run this plugin!")

from . import __version__


class PluginApp(PluginConfig):
    default = True
    name = "pretix_mailwizz"
    verbose_name = "pretix MailWizz Newsletter"

    class PretixPluginMeta:
        name = _("MailWizz Newsletter")
        author = "pretix-mailwizz contributors"
        version = __version__
        category = "INTEGRATION"
        visible = True
        description = _(
            "Adds an optional newsletter opt-in checkbox to the checkout. "
            "If the customer actively consents, the email address is "
            "subscribed to a configurable MailWizz list after the order is "
            "placed, triggering MailWizz's double opt-in process."
        )
        # Per-event activation, with organizer-wide default settings.
        level = PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID
        compatibility = "pretix>=2025.10"

    def ready(self):
        from . import (
            signals,  # noqa: F401
            tasks,  # noqa: F401
        )
