from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db.models import Sum, Avg, Max, Min, Count, Q
from django.utils import timezone
from datetime import timedelta
from .models import Device, EnergyReading, RateConfiguration, FirmwareVersion, OTAUpdate
from .serializers import (
    DeviceSerializer, DeviceListSerializer, EnergyReadingSerializer,
    EnergyReadingCreateSerializer, RateConfigurationSerializer,
    FirmwareVersionSerializer, FirmwareVersionListSerializer,
    OTAUpdateSerializer, OTAUpdateCreateSerializer,
    DeviceStatisticsSerializer, EnergyStatisticsSerializer
)


class DeviceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Device model
    Supports CRUD operations and custom actions for device management
    """
    queryset = Device.objects.all()
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'mac_address', 'token']
    ordering_fields = ['name', 'created_at', 'last_seen', 'status']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return DeviceListSerializer
        return DeviceSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by status
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        # Filter online devices
        online_only = self.request.query_params.get('online', None)
        if online_only == 'true':
            threshold = timezone.now() - timedelta(seconds=30)
            queryset = queryset.filter(last_seen__gte=threshold)
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get statistics for a specific device"""
        device = self.get_object()
        
        # Get date range from query params (default: last 24 hours)
        hours = int(request.query_params.get('hours', 24))
        start_time = timezone.now() - timedelta(hours=hours)
        
        readings = device.readings.filter(timestamp__gte=start_time)
        
        stats = readings.aggregate(
            total_energy=Sum('energy'),
            average_power=Avg('power'),
            peak_power=Max('power'),
            min_power=Min('power'),
            total_readings=Count('id'),
            average_voltage=Avg('voltage'),
            average_current=Avg('current'),
            average_power_factor=Avg('power_factor')
        )
        
        # Calculate cost
        default_rate = device.rates.filter(is_default=True, is_active=True).first()
        total_cost = 0
        if default_rate and stats['total_energy']:
            total_cost = float(stats['total_energy']) * float(default_rate.rate_per_kwh)
        
        stats['total_cost'] = total_cost
        stats['rate_per_kwh'] = float(default_rate.rate_per_kwh) if default_rate else None
        stats['currency'] = 'PHP'
        stats['date_range'] = {
            'start': start_time,
            'end': timezone.now(),
            'hours': hours
        }
        
        return Response(stats)
    
    @action(detail=True, methods=['get'])
    def readings(self, request, pk=None):
        """Get energy readings for a specific device"""
        device = self.get_object()
        
        # Get date range from query params
        hours = int(request.query_params.get('hours', 24))
        start_time = timezone.now() - timedelta(hours=hours)
        
        readings = device.readings.filter(timestamp__gte=start_time)
        
        # Pagination
        page = self.paginate_queryset(readings)
        if page is not None:
            serializer = EnergyReadingSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = EnergyReadingSerializer(readings, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def reset_energy(self, request, pk=None):
        """Delete all stored readings for the device and send reset_energy command to the PZEM via WebSocket"""
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        device = self.get_object()

        # Clear all stored readings from the database
        deleted_count, _ = device.readings.all().delete()

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'device_{device.token}',
            {
                'type': 'command',
                'command': 'reset_energy',
            }
        )
        return Response({
            'status': 'reset_sent',
            'device': device.name,
            'message': f'Energy counter reset — {deleted_count} readings deleted from database.',
        })
    
    @action(detail=False, methods=['get'])
    def statistics_all(self, request):
        """Get overall statistics for all devices"""
        devices = self.get_queryset()
        
        total_devices = devices.count()
        threshold = timezone.now() - timedelta(seconds=30)
        online_devices = devices.filter(last_seen__gte=threshold).count()
        offline_devices = devices.filter(
            Q(last_seen__lt=threshold) | Q(last_seen__isnull=True)
        ).count()
        error_devices = devices.filter(status='error').count()
        
        stats = {
            'total_devices': total_devices,
            'online_devices': online_devices,
            'offline_devices': offline_devices,
            'error_devices': error_devices
        }
        
        serializer = DeviceStatisticsSerializer(stats)
        return Response(serializer.data)
    
    @action(detail=True, methods=['get'])
    def cost_projection(self, request, pk=None):
        """Get cost projections for device"""
        from .analytics import CostProjectionAnalyzer
        
        device = self.get_object()
        hours = int(request.query_params.get('hours', 24))
        
        projection = CostProjectionAnalyzer.project_daily_cost(device, hours)
        return Response(projection)
    
    @action(detail=True, methods=['get'])
    def usage_pattern(self, request, pk=None):
        """Get usage patterns for device"""
        from .analytics import UsagePatternAnalyzer
        
        device = self.get_object()
        pattern_type = request.query_params.get('type', 'hourly')
        days = int(request.query_params.get('days', 7))
        
        if pattern_type == 'hourly':
            pattern = UsagePatternAnalyzer.analyze_hourly_pattern(device, days)
        else:
            pattern = UsagePatternAnalyzer.analyze_daily_pattern(device, days)
        
        return Response(pattern)
    
    @action(detail=True, methods=['get'])
    def detect_anomalies(self, request, pk=None):
        """Detect anomalies in device consumption"""
        from .analytics import AnomalyDetector
        
        device = self.get_object()
        hours = int(request.query_params.get('hours', 24))
        
        spikes = AnomalyDetector.detect_power_spikes(device, hours)
        unusual = AnomalyDetector.detect_unusual_consumption(device, hours)
        
        return Response({
            'power_spikes': spikes,
            'unusual_consumption': unusual
        })
    
    @action(detail=True, methods=['get'])
    def detect_appliances(self, request, pk=None):
        """Detect likely appliances based on power consumption"""
        from .analytics import ApplianceDetector
        
        device = self.get_object()
        hours = int(request.query_params.get('hours', 1))
        
        appliances = ApplianceDetector.detect_appliances(device, hours)
        events = ApplianceDetector.detect_power_state_changes(device, 24)
        
        return Response({
            'likely_appliances': appliances,
            'recent_events': events
        })
    
    @action(detail=True, methods=['post'])
    def compare_periods(self, request, pk=None):
        """Compare energy consumption between two periods"""
        from .analytics import CostProjectionAnalyzer
        from datetime import datetime
        
        device = self.get_object()
        
        # Parse dates from request
        p1_start = datetime.fromisoformat(request.data.get('period1_start'))
        p1_end = datetime.fromisoformat(request.data.get('period1_end'))
        p2_start = datetime.fromisoformat(request.data.get('period2_start'))
        p2_end = datetime.fromisoformat(request.data.get('period2_end'))
        
        comparison = CostProjectionAnalyzer.compare_periods(
            device, p1_start, p1_end, p2_start, p2_end
        )
        
        return Response(comparison)

    @action(detail=True, methods=['post'])
    def push_lcd_templates(self, request, pk=None):
        """
        Save lcd_templates to the device and push the config live to the ESP via WebSocket.
        Expected body: { "lcd_templates": [...] }
        """
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        device = self.get_object()
        templates = request.data.get('lcd_templates', None)

        if templates is None:
            return Response({'error': 'lcd_templates is required'}, status=status.HTTP_400_BAD_REQUEST)

        device.lcd_templates = templates
        device.save(update_fields=['lcd_templates'])

        # Push updated config to the device if it is connected
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'device_{device.token}',
            {'type': 'push_config'}
        )

        serializer = self.get_serializer(device)
        return Response(serializer.data)


class EnergyReadingViewSet(viewsets.ModelViewSet):
    """
    ViewSet for EnergyReading model
    Supports CRUD operations and filtering by device and time range
    """
    queryset = EnergyReading.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['timestamp', 'power', 'energy']
    ordering = ['-timestamp']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return EnergyReadingCreateSerializer
        return EnergyReadingSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by device
        device_id = self.request.query_params.get('device', None)
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        
        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)
        
        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)
        
        # Filter by hours (e.g., last 24 hours)
        hours = self.request.query_params.get('hours', None)
        if hours:
            start_time = timezone.now() - timedelta(hours=int(hours))
            queryset = queryset.filter(timestamp__gte=start_time)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get statistics for energy readings"""
        queryset = self.get_queryset()
        
        stats = queryset.aggregate(
            total_energy=Sum('energy'),
            average_power=Avg('power'),
            peak_power=Max('power'),
            min_power=Min('power'),
            total_readings=Count('id')
        )
        
        # Calculate cost (using first device's default rate as example)
        if queryset.exists():
            first_reading = queryset.first()
            default_rate = first_reading.device.rates.filter(
                is_default=True, is_active=True
            ).first()
            
            if default_rate and stats['total_energy']:
                stats['total_cost'] = float(stats['total_energy']) * float(default_rate.rate_per_kwh)
            else:
                stats['total_cost'] = 0
        else:
            stats['total_cost'] = 0
        
        # Get date range
        date_range = queryset.aggregate(
            start=Min('timestamp'),
            end=Max('timestamp')
        )
        stats['date_range'] = date_range
        
        serializer = EnergyStatisticsSerializer(stats)
        return Response(serializer.data)


class RateConfigurationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for RateConfiguration model
    Supports CRUD operations and filtering by device
    """
    queryset = RateConfiguration.objects.all()
    serializer_class = RateConfigurationSerializer
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['rate_per_kwh', 'created_at']
    ordering = ['-is_default', '-is_active', '-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by device
        device_id = self.request.query_params.get('device', None)
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        
        # Filter by active status
        is_active = self.request.query_params.get('is_active', None)
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')
        
        return queryset
    
    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set this rate as default for the device"""
        rate = self.get_object()
        rate.is_default = True
        rate.save()
        
        serializer = self.get_serializer(rate)
        return Response(serializer.data)


class FirmwareVersionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for FirmwareVersion model
    Supports CRUD operations for firmware management
    """
    queryset = FirmwareVersion.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['version', 'created_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        if self.action == 'list':
            return FirmwareVersionListSerializer
        return FirmwareVersionSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by stability
        is_stable = self.request.query_params.get('is_stable', None)
        if is_stable is not None:
            queryset = queryset.filter(is_stable=is_stable.lower() == 'true')
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def latest(self, request):
        """Get the latest firmware version"""
        latest_version = self.get_queryset().filter(is_latest=True).first()
        if latest_version:
            serializer = self.get_serializer(latest_version)
            return Response(serializer.data)
        return Response({'error': 'No latest version available'}, status=404)
    
    @action(detail=True, methods=['post'])
    def set_latest(self, request, pk=None):
        """Set this version as the latest"""
        version = self.get_object()
        version.is_latest = True
        version.save()
        
        serializer = self.get_serializer(version)
        return Response(serializer.data)


class OTAUpdateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for OTAUpdate model
    Supports CRUD operations and monitoring OTA updates
    """
    queryset = OTAUpdate.objects.all()
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['initiated_at', 'status']
    ordering = ['-initiated_at']
    
    def get_serializer_class(self):
        if self.action == 'create':
            return OTAUpdateCreateSerializer
        return OTAUpdateSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by device
        device_id = self.request.query_params.get('device', None)
        if device_id:
            queryset = queryset.filter(device_id=device_id)
        
        # Filter by status
        status_filter = self.request.query_params.get('status', None)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        
        return queryset

    def perform_create(self, serializer):
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        
        update = serializer.save()
        
        # Send WebSocket command to the device to trigger update
        channel_layer = get_channel_layer()
        request = self.request
        
        device = update.device
        firmware_version = update.firmware_version
        
        if firmware_version.firmware_file:
            # Set status to downloading since we are sending the command
            update.status = 'downloading'
            update.started_at = timezone.now()
            update.save()
            
            # Build global URL for the firmware binary
            url = request.build_absolute_uri(firmware_version.firmware_file.url)
            
            # Send message to the specific device's websocket group
            async_to_sync(channel_layer.group_send)(
                f'device_{device.token}',
                {
                    'type': 'command',
                    'command': 'ota_update',
                    'url': url,
                    'update_id': str(update.id)
                }
            )
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel a pending OTA update"""
        update = self.get_object()
        
        if update.status not in ['pending', 'downloading']:
            return Response(
                {'error': 'Can only cancel pending or downloading updates'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        update.status = 'cancelled'
        update.save()
        
        serializer = self.get_serializer(update)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry a failed OTA update"""
        update = self.get_object()
        
        if update.status != 'failed':
            return Response(
                {'error': 'Can only retry failed updates'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create new update with same parameters
        new_update = OTAUpdate.objects.create(
            device=update.device,
            firmware_version=update.firmware_version,
            previous_version=update.device.firmware_version
        )
        
        serializer = self.get_serializer(new_update)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

