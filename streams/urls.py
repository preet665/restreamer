from django.urls import path

from . import views

app_name = "streams"

urlpatterns = [
    path("info", views.stream_info, name="stream-info"),
    path("stream-url", views.get_stream_url, name="stream-url"),
]
