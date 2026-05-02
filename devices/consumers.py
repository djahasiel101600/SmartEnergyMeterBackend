"""
WebSocket consumers for real-time communication.
"""

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from datetime import datetime
import json
import logging

from .models import Device, EnergyReading
from .serializers import EnergyReadingSerializer

logger = logging.getLogger(__name__)


class DeviceConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for ESP8266 device connections.
    Handles incoming sensor data and commands to devices.
    
    Expected WebSocket URL: ws://backend/ws/device/<device_token>/
    """
    
    async def connect(self):
        """Handle WebSocket connection from ESP8266"""
        self.device_token = self.scope['url_route']['kwargs']['device_token']
        self.device = None
        self.device_group_name = f'device_{self.device_token}'
        
        # Authenticate device by token
        device = await self.get_device_by_token(self.device_token)
        
        if not device:
            logger.warning(f"Device connection rejected: invalid token {self.device_token}")
            await self.close(code=4001)
            return
        
        self.device = device
        
        # Join device-specific group
        await self.channel_layer.group_add(
            self.device_group_name,
            self.channel_name
        )
        
        # Accept connection
        await self.accept()
        
        # Mark device as online
        await self.mark_device_online(device)
        
        # Notify frontend that device is online
        await self.notify_device_status('online')
        
        # Push current config (including lcd_templates) to the device
        await self.send_device_config(device)
        
        logger.info(f"Device connected: {device.name} ({device.mac_address})")
        
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if self.device:
            # Mark device as offline
            await self.mark_device_offline(self.device)
            
            # Notify frontend that device is offline
            await self.notify_device_status('offline')
            
            logger.info(f"Device disconnected: {self.device.name}")
        
        # Leave device group
        if hasattr(self, 'device_group_name'):
            await self.channel_layer.group_discard(
                self.device_group_name,
                self.channel_name
            )
        
    async def receive(self, text_data):
        """
        Receive message from ESP8266
        
        Expected JSON format:
        {
            "type": "reading",
            "data": {
                "voltage": 220.5,
                "current": 1.234,
                "power": 272.1,
                "energy": 1.234,
                "frequency": 50.0,
                "power_factor": 0.99
            },
            "timestamp": "2026-05-01T20:30:00Z"  # Optional, will use server time if not provided
        }
        """
        try:
            message = json.loads(text_data)
            message_type = message.get('type')
            
            if message_type == 'reading':
                # Process energy reading
                await self.handle_energy_reading(message)
                
            elif message_type == 'status':
                # Process device status update
                await self.handle_status_update(message)
                
            elif message_type == 'error':
                # Process device error
                await self.handle_device_error(message)
                
            elif message_type == 'heartbeat':
                # Update last_seen timestamp
                await self.update_last_seen(self.device)
                await self.send(text_data=json.dumps({
                    'type': 'heartbeat_ack',
                    'timestamp': timezone.now().isoformat()
                }))
                
            elif message_type == 'ota_progress':
                # Handle OTA progress from device
                await self.handle_ota_progress(message)
                
            else:
                logger.warning(f"Unknown message type from device {self.device.name}: {message_type}")
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown message type: {message_type}'
                }))
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from device {self.device.name}: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"Error processing message from device {self.device.name}: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Internal server error'
            }))
    
    async def handle_energy_reading(self, message):
        """Process and save energy reading"""
        try:
            data = message.get('data', {})
            timestamp_str = message.get('timestamp')
            
            # Parse timestamp or use current time
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                except:
                    timestamp = timezone.now()
            else:
                timestamp = timezone.now()
            
            # Create reading in database
            reading = await self.create_energy_reading(
                device=self.device,
                voltage=data.get('voltage'),
                current=data.get('current'),
                power=data.get('power'),
                energy=data.get('energy'),
                frequency=data.get('frequency'),
                power_factor=data.get('power_factor'),
                timestamp=timestamp
            )
            
            if reading:
                # Send confirmation to device
                await self.send(text_data=json.dumps({
                    'type': 'reading_ack',
                    'id': str(reading.id),
                    'timestamp': reading.timestamp.isoformat()
                }))
                
                # Broadcast to frontend
                await self.broadcast_energy_update(reading)
                
                logger.debug(f"Reading saved from {self.device.name}: {data.get('power')}W")
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': 'Failed to save reading'
                }))
                
        except Exception as e:
            logger.error(f"Error handling energy reading: {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))
    
    async def handle_status_update(self, message):
        """Handle device status update"""
        try:
            data = message.get('data', {})
            firmware_version = data.get('firmware_version')
            mac_address = data.get('mac_address')
            
            # Update device info
            completed_ota = await self.update_device_info(
                self.device,
                firmware_version=firmware_version,
                mac_address=mac_address
            )
            
            if completed_ota:
                await self.channel_layer.group_send(
                    'energy_updates',
                    {
                        'type': 'ota_update_progress',
                        'device_id': str(self.device.id),
                        'progress': 100,
                        'status': 'completed',
                        'timestamp': timezone.now().isoformat()
                    }
                )
                
            await self.send(text_data=json.dumps({
                'type': 'status_ack',
                'message': 'Status updated'
            }))
            
        except Exception as e:
            logger.error(f"Error handling status update: {e}")
    
    async def handle_device_error(self, message):
        """Handle device error message"""
        error_data = message.get('data', {})
        error_message = error_data.get('message', 'Unknown error')
        
        logger.error(f"Device {self.device.name} reported error: {error_message}")
        
        # Mark device status as error
        await self.mark_device_error(self.device, error_message)
        
        # Notify frontend
        await self.notify_device_error(error_message)
    
    async def handle_ota_progress(self, message):
        """Handle OTA download progress"""
        progress = message.get('progress', 0)
        await self.update_ota_progress(self.device, progress)
        
        # Notify frontend directly to update UI immediately
        await self.channel_layer.group_send(
            'energy_updates',
            {
                'type': 'ota_update_progress',
                'device_id': str(self.device.id),
                'progress': progress,
                'status': 'downloading',
                'timestamp': timezone.now().isoformat()
            }
        )
    
    async def notify_device_status(self, status):
        """Notify frontend about device status change"""
        await self.channel_layer.group_send(
            'energy_updates',
            {
                'type': 'device_status',
                'device_id': str(self.device.id),
                'device_name': self.device.name,
                'status': status,
                'timestamp': timezone.now().isoformat()
            }
        )
    
    async def notify_device_error(self, error_message):
        """Notify frontend about device error"""
        await self.channel_layer.group_send(
            'energy_updates',
            {
                'type': 'notification',
                'notification_type': 'device_error',
                'device_id': str(self.device.id),
                'device_name': self.device.name,
                'message': error_message,
                'timestamp': timezone.now().isoformat()
            }
        )
    
    async def broadcast_energy_update(self, reading):
        """Broadcast energy reading to frontend clients"""
        # Get default rate for cost calculation
        default_rate = await self.get_default_rate(self.device)
        cost = None
        if default_rate:
            cost = float(reading.energy) * float(default_rate.rate_per_kwh)
        
        await self.channel_layer.group_send(
            'energy_updates',
            {
                'type': 'energy_update',
                'device_id': str(self.device.id),
                'device_name': self.device.name,
                'reading_id': str(reading.id),
                'data': {
                    'voltage': float(reading.voltage),
                    'current': float(reading.current),
                    'power': float(reading.power),
                    'energy': float(reading.energy),
                    'frequency': float(reading.frequency),
                    'power_factor': float(reading.power_factor),
                    'cost': cost,
                    'currency': 'PHP'
                },
                'timestamp': reading.timestamp.isoformat()
            }
        )
    
    async def command(self, event):
        """Send command to device (e.g., OTA update, LCD config, reset)"""
        await self.send(text_data=json.dumps(event))

    async def push_config(self, event):
        """Push config update to device — triggered via channel group_send"""
        await self.send_device_config(self.device)

    async def send_device_config(self, device):
        """Send the current device config (including lcd_templates) to the ESP"""
        config = await self.get_device_config(device)
        await self.send(text_data=json.dumps({
            'type': 'config',
            'config': config
        }))

    @database_sync_to_async
    def get_device_config(self, device):
        """Fetch device config fields to push to the ESP"""
        device.refresh_from_db()
        return {
            'lcd_enabled': device.lcd_enabled,
            'lcd_rotation_interval': device.lcd_rotation_interval * 1000,  # ms for ESP
            'lcd_templates': device.lcd_templates,
            'nominal_voltage': device.nominal_voltage,
        }
    
    # Database operations (async wrappers)
    
    @database_sync_to_async
    def get_device_by_token(self, token):
        """Get device by authentication token"""
        try:
            return Device.objects.get(token=token)
        except Device.DoesNotExist:
            return None
    
    @database_sync_to_async
    def mark_device_online(self, device):
        """Mark device as online"""
        device.status = 'online'
        device.last_seen = timezone.now()
        device.save(update_fields=['status', 'last_seen'])
    
    @database_sync_to_async
    def mark_device_offline(self, device):
        """Mark device as offline"""
        device.status = 'offline'
        device.last_seen = timezone.now()
        device.save(update_fields=['status', 'last_seen'])
    
    @database_sync_to_async
    def mark_device_error(self, device, error_message):
        """Mark device as error state"""
        device.status = 'error'
        device.last_seen = timezone.now()
        device.save(update_fields=['status', 'last_seen'])
    
    @database_sync_to_async
    def update_last_seen(self, device):
        """Update device last_seen timestamp"""
        device.last_seen = timezone.now()
        device.save(update_fields=['last_seen'])
    
    @database_sync_to_async
    def update_device_info(self, device, firmware_version=None, mac_address=None):
        """Update device information. Returns True if this completed an OTA update."""
        ota_completed = False
        if firmware_version and firmware_version != device.firmware_version:
            device.firmware_version = firmware_version
            
            # Check if this completes a pending OTA update
            from .models import OTAUpdate
            pending_updates = OTAUpdate.objects.filter(
                device=device,
                status__in=['pending', 'downloading', 'installing']
            )
            for update in pending_updates:
                if update.firmware_version.version == firmware_version:
                    update.status = 'completed'
                    update.progress = 100
                    update.completed_at = timezone.now()
                    update.save()
                    ota_completed = True
                    
        if mac_address:
            device.mac_address = mac_address
        device.last_seen = timezone.now()
        device.save()
        return ota_completed
    
    @database_sync_to_async
    def update_ota_progress(self, device, progress):
        """Update progress on pending OTA update"""
        from .models import OTAUpdate
        updates = OTAUpdate.objects.filter(
            device=device,
            status__in=['pending', 'downloading', 'installing']
        )
        for update in updates:
            update.status = 'downloading' if progress < 100 else 'installing'
            update.progress = progress
            update.save(update_fields=['status', 'progress'])

    @database_sync_to_async
    def create_energy_reading(self, device, voltage, current, power, energy, frequency, power_factor, timestamp):
        """Create energy reading in database"""
        try:
            reading = EnergyReading.objects.create(
                device=device,
                voltage=voltage,
                current=current,
                power=power,
                energy=energy,
                frequency=frequency,
                power_factor=power_factor,
                timestamp=timestamp
            )
            return reading
        except Exception as e:
            logger.error(f"Error creating energy reading: {e}")
            return None
    
    @database_sync_to_async
    def get_default_rate(self, device):
        """Get default rate configuration for device"""
        try:
            return device.rates.filter(is_default=True, is_active=True).first()
        except:
            return None


class FrontendConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for frontend client connections.
    Sends real-time energy updates and notifications.
    
    Expected WebSocket URL: ws://backend/ws/energy/
    """
    
    async def connect(self):
        """Handle WebSocket connection from frontend"""
        self.energy_group_name = 'energy_updates'
        self.subscribed_devices = set()
        
        # Join energy updates group
        await self.channel_layer.group_add(
            self.energy_group_name,
            self.channel_name
        )
        
        # Accept connection
        await self.accept()
        
        # TODO: Implement session-based authentication if needed
        # For now, accepting all connections (single-user system)
        
        logger.info("Frontend client connected")
        
        # Send initial connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection',
            'status': 'connected',
            'message': 'Connected to energy monitoring WebSocket',
            'timestamp': timezone.now().isoformat()
        }))
        
    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave energy updates group
        await self.channel_layer.group_discard(
            self.energy_group_name,
            self.channel_name
        )
        
        logger.info("Frontend client disconnected")
        
    async def receive(self, text_data):
        """
        Receive message from frontend
        
        Supported message types:
        - subscribe: Subscribe to specific device updates
        - unsubscribe: Unsubscribe from device updates
        - request_status: Request current status of all devices
        """
        try:
            message = json.loads(text_data)
            message_type = message.get('type')
            
            if message_type == 'subscribe':
                # Subscribe to specific device
                device_id = message.get('device_id')
                if device_id:
                    self.subscribed_devices.add(device_id)
                    await self.send(text_data=json.dumps({
                        'type': 'subscription_ack',
                        'device_id': device_id,
                        'message': 'Subscribed to device updates'
                    }))
                    
            elif message_type == 'unsubscribe':
                # Unsubscribe from device
                device_id = message.get('device_id')
                if device_id and device_id in self.subscribed_devices:
                    self.subscribed_devices.remove(device_id)
                    await self.send(text_data=json.dumps({
                        'type': 'unsubscription_ack',
                        'device_id': device_id,
                        'message': 'Unsubscribed from device updates'
                    }))
                    
            elif message_type == 'request_status':
                # Send current status of all devices
                devices_status = await self.get_all_devices_status()
                await self.send(text_data=json.dumps({
                    'type': 'devices_status',
                    'devices': devices_status,
                    'timestamp': timezone.now().isoformat()
                }))
                
            elif message_type == 'ping':
                # Heartbeat/ping response
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON from frontend: {e}")
        except Exception as e:
            logger.error(f"Error processing frontend message: {e}")
    
    async def energy_update(self, event):
        """
        Send energy update to frontend
        Called by DeviceConsumer when new reading arrives
        """
        # If frontend subscribed to specific devices, filter updates
        if self.subscribed_devices and event.get('device_id') not in self.subscribed_devices:
            return
        
        await self.send(text_data=json.dumps(event))
    
    async def device_status(self, event):
        """
        Send device status update to frontend
        Called when device connects/disconnects
        """
        await self.send(text_data=json.dumps(event))
    
    async def ota_update_progress(self, event):
        """
        Send OTA update progress to frontend
        Called when device reports OTA progress
        """
        await self.send(text_data=json.dumps(event))
    
    async def notification(self, event):
        """
        Send notification to frontend
        Called for alerts, errors, and important events
        """
        await self.send(text_data=json.dumps(event))
    
    # Database operations
    
    @database_sync_to_async
    def get_all_devices_status(self):
        """Get current status of all devices"""
        from .serializers import DeviceListSerializer
        devices = Device.objects.all()
        serializer = DeviceListSerializer(devices, many=True)
        return serializer.data
