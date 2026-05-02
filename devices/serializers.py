from rest_framework import serializers
from .models import Device, EnergyReading, RateConfiguration, FirmwareVersion, OTAUpdate
from django.utils import timezone


class DeviceSerializer(serializers.ModelSerializer):
    """Device serializer with computed fields"""
    is_online = serializers.SerializerMethodField()
    total_readings = serializers.SerializerMethodField()
    latest_reading = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            'id', 'name', 'token', 'mac_address', 'status', 'last_seen',
            'firmware_version', 'lcd_enabled', 'lcd_rotation_interval', 'lcd_templates',
            'nominal_voltage',
            'is_online', 'total_readings', 'latest_reading',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'token', 'mac_address', 'last_seen', 'created_at', 'updated_at']
    
    def get_is_online(self, obj):
        return obj.is_online()
    
    def get_total_readings(self, obj):
        return obj.readings.count()
    
    def get_latest_reading(self, obj):
        latest = obj.readings.first()
        if latest:
            return {
                'timestamp': latest.timestamp,
                'power': float(latest.power),
                'energy': float(latest.energy),
                'voltage': float(latest.voltage),
                'current': float(latest.current)
            }
        return None


class DeviceListSerializer(serializers.ModelSerializer):
    """Lightweight device serializer for list views"""
    is_online = serializers.SerializerMethodField()
    
    class Meta:
        model = Device
        fields = [
            'id', 'name', 'mac_address', 'status', 'last_seen',
            'firmware_version', 'is_online', 'created_at'
        ]
    
    def get_is_online(self, obj):
        return obj.is_online()


class EnergyReadingSerializer(serializers.ModelSerializer):
    """Energy reading serializer"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    cost = serializers.SerializerMethodField()
    
    class Meta:
        model = EnergyReading
        fields = [
            'id', 'device', 'device_name', 'voltage', 'current', 'power',
            'energy', 'frequency', 'power_factor', 'timestamp', 'cost',
            'created_at'
        ]
        read_only_fields = ['id', 'created_at']
    
    def get_cost(self, obj):
        """Calculate cost using device's default rate"""
        try:
            default_rate = obj.device.rates.filter(is_default=True, is_active=True).first()
            if default_rate:
                return float(obj.calculate_cost(default_rate.rate_per_kwh))
            return None
        except:
            return None


class EnergyReadingCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating energy readings (used by WebSocket/API)"""
    
    class Meta:
        model = EnergyReading
        fields = [
            'device', 'voltage', 'current', 'power', 'energy',
            'frequency', 'power_factor', 'timestamp'
        ]
    
    def validate_timestamp(self, value):
        """Ensure timestamp is not in the future"""
        if value > timezone.now():
            raise serializers.ValidationError("Timestamp cannot be in the future")
        return value
    
    def validate_voltage(self, value):
        """Validate voltage range (0-300V)"""
        if value < 0 or value > 300:
            raise serializers.ValidationError("Voltage must be between 0 and 300V")
        return value
    
    def validate_current(self, value):
        """Validate current range (0-100A)"""
        if value < 0 or value > 100:
            raise serializers.ValidationError("Current must be between 0 and 100A")
        return value
    
    def validate_power_factor(self, value):
        """Validate power factor range (0-1)"""
        if value < 0 or value > 1:
            raise serializers.ValidationError("Power factor must be between 0 and 1")
        return value


class RateConfigurationSerializer(serializers.ModelSerializer):
    """Rate configuration serializer"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    
    class Meta:
        model = RateConfiguration
        fields = [
            'id', 'device', 'device_name', 'rate_per_kwh', 'name', 'description',
            'start_time', 'end_time', 'is_active', 'is_default',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def validate_rate_per_kwh(self, value):
        """Validate rate is positive"""
        if value <= 0:
            raise serializers.ValidationError("Rate must be greater than 0")
        return value
    
    def validate(self, data):
        """Validate time range if provided"""
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        
        if (start_time and not end_time) or (end_time and not start_time):
            raise serializers.ValidationError(
                "Both start_time and end_time must be provided for time-based rates"
            )
        
        return data


class FirmwareVersionSerializer(serializers.ModelSerializer):
    """Firmware version serializer"""
    file_size_display = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    
    class Meta:
        model = FirmwareVersion
        fields = [
            'id', 'version', 'description', 'firmware_file', 'file_size',
            'file_size_display', 'checksum', 'is_stable', 'is_latest',
            'min_compatible_version', 'download_url', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_file_size_display(self, obj):
        size_kb = obj.file_size / 1024
        if size_kb < 1024:
            return f'{size_kb:.2f} KB'
        return f'{size_kb / 1024:.2f} MB'
    
    def get_download_url(self, obj):
        request = self.context.get('request')
        if request and obj.firmware_file:
            return request.build_absolute_uri(obj.firmware_file.url)
        return None


class FirmwareVersionListSerializer(serializers.ModelSerializer):
    """Lightweight firmware version serializer for list views"""
    file_size_display = serializers.SerializerMethodField()
    
    class Meta:
        model = FirmwareVersion
        fields = [
            'id', 'version', 'file_size_display', 'is_stable',
            'is_latest', 'created_at'
        ]
    
    def get_file_size_display(self, obj):
        size_kb = obj.file_size / 1024
        if size_kb < 1024:
            return f'{size_kb:.2f} KB'
        return f'{size_kb / 1024:.2f} MB'


class OTAUpdateSerializer(serializers.ModelSerializer):
    """OTA update serializer"""
    device_name = serializers.CharField(source='device.name', read_only=True)
    firmware_version_number = serializers.CharField(source='firmware_version.version', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration = serializers.SerializerMethodField()
    
    class Meta:
        model = OTAUpdate
        fields = [
            'id', 'device', 'device_name', 'firmware_version',
            'firmware_version_number', 'status', 'status_display', 'progress',
            'error_message', 'initiated_at', 'started_at', 'completed_at',
            'previous_version', 'duration'
        ]
        read_only_fields = [
            'id', 'initiated_at', 'started_at', 'completed_at',
            'previous_version'
        ]
    
    def get_duration(self, obj):
        """Calculate update duration in seconds"""
        if obj.completed_at and obj.started_at:
            return (obj.completed_at - obj.started_at).total_seconds()
        elif obj.started_at:
            return (timezone.now() - obj.started_at).total_seconds()
        return None


class OTAUpdateCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating OTA updates"""
    
    class Meta:
        model = OTAUpdate
        fields = ['device', 'firmware_version']
    
    def validate(self, data):
        """Validate OTA update can be created"""
        device = data['device']
        firmware_version = data['firmware_version']
        
        # Check if device is online
        if not device.is_online():
            raise serializers.ValidationError("Device must be online to initiate OTA update")
        
        # Check if there's already a pending/in-progress update
        existing_update = OTAUpdate.objects.filter(
            device=device,
            status__in=['pending', 'downloading', 'installing']
        ).first()
        
        if existing_update:
            raise serializers.ValidationError(
                f"Device already has an update in progress: {existing_update.status}"
            )
        
        # Store previous version
        data['previous_version'] = device.firmware_version
        
        return data


# Statistics and Analytics Serializers

class DeviceStatisticsSerializer(serializers.Serializer):
    """Device statistics serializer"""
    total_devices = serializers.IntegerField()
    online_devices = serializers.IntegerField()
    offline_devices = serializers.IntegerField()
    error_devices = serializers.IntegerField()


class EnergyStatisticsSerializer(serializers.Serializer):
    """Energy statistics serializer"""
    total_energy = serializers.DecimalField(max_digits=12, decimal_places=3)
    total_cost = serializers.DecimalField(max_digits=12, decimal_places=2)
    average_power = serializers.DecimalField(max_digits=10, decimal_places=2)
    peak_power = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_readings = serializers.IntegerField()
    date_range = serializers.DictField()
