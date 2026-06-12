from django.urls import path

from .views import EventSettingsView, OrganizerSettingsView, TestConnectionView

urlpatterns = [
    path(
        "control/organizer/<str:organizer>/mailwizz/",
        OrganizerSettingsView.as_view(),
        name="organizer.settings",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/settings/mailwizz/",
        EventSettingsView.as_view(),
        name="event.settings",
    ),
    path(
        "control/event/<str:organizer>/<str:event>/settings/mailwizz/test/",
        TestConnectionView.as_view(),
        name="event.test",
    ),
]
