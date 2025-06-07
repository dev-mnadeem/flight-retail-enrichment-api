from django.urls import path

from . import views

app_name = "flights"

urlpatterns = [
    path("", views.FlightListView.as_view(), name="flight-list"),
    path("tasks/", views.TaskListView.as_view(), name="task-list"),
]
