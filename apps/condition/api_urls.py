from django.urls import path

from .api import MeasurementAPIView

urlpatterns = [
    path("mesures/", MeasurementAPIView.as_view(), name="api-measurements"),
]
