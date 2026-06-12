__version__ = "1.0.0"


def __getattr__(name):
    # Lazily resolve the AppConfig for the "pretix_mailwizz:PluginApp"
    # entry point without importing Django at package import time.
    if name == "PluginApp":
        from .apps import PluginApp

        return PluginApp
    raise AttributeError(name)
