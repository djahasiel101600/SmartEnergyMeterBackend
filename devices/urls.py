from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    DeviceViewSet,
    EnergyReadingViewSet,
    RateConfigurationViewSet,
    FirmwareVersionViewSet,
    OTAUpdateViewSet
)

# Create a router and register viewsets
router = DefaultRouter()
router.register(r'devices', DeviceViewSet, basename='device')
router.register(r'readings', EnergyReadingViewSet, basename='energyreading')
router.register(r'rates', RateConfigurationViewSet, basename='rateconfiguration')
router.register(r'firmware', FirmwareVersionViewSet, basename='firmwareversion')
router.register(r'ota-updates', OTAUpdateViewSet, basename='otaupdate')

urlpatterns = [
    path('', include(router.urls)),
]
