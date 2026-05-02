"""
WebSocket URL routing for backend project.
"""

from django.urls import path
from devices import consumers

websocket_urlpatterns = [
    # WebSocket endpoint for ESP8266 devices
    # Format: ws://backend/ws/device/<device_token>/
    path('ws/device/<str:device_token>/', consumers.DeviceConsumer.as_asgi()),
    
    # WebSocket endpoint for frontend clients
    # Format: ws://backend/ws/energy/
    path('ws/energy/', consumers.FrontendConsumer.as_asgi()),
]
