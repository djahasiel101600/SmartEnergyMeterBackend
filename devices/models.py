from django.db import models
from django.utils import timezone
import uuid


import secrets

class Device(models.Model):
    """ESP8266 Device model"""
    STATUS_CHOICES = [
        ('online', 'Online'),
        ('offline', 'Offline'),
        ('error', 'Error'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="Device name")
    token = models.CharField(max_length=64, unique=True, db_index=True, blank=True, help_text="WebSocket authentication token")
    mac_address = models.CharField(max_length=17, unique=True, blank=True, null=True, help_text="MAC address of ESP8266")
    
    # Status
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='offline')
    last_seen = models.DateTimeField(null=True, blank=True, help_text="Last connection time")
    firmware_version = models.CharField(max_length=20, blank=True, default='', help_text="Current firmware version")
    
    # LCD Configuration
    lcd_enabled = models.BooleanField(default=True, help_text="Enable/disable LCD display")
    lcd_rotation_interval = models.IntegerField(default=5, help_text="LCD screen rotation interval in seconds")
    lcd_templates = models.JSONField(
        default=list, 
        blank=True, 
        help_text="Array of LCD screen templates. Example: [{'line1':'{v}V {i}A', 'line2': '{p}W'}]"
    )
    nominal_voltage = models.FloatField(
        default=230.0,
        help_text="Nominal mains voltage for this location (V). Used for stability thresholds (±10%)."
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'last_seen']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.mac_address or 'No MAC'})"
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_hex(16)
        super().save(*args, **kwargs)
    
    def is_online(self):
        """Check if device is online (seen in last 30 seconds)"""
        if not self.last_seen:
            return False
        return (timezone.now() - self.last_seen).total_seconds() < 30


class EnergyReading(models.Model):
    """Energy readings from PZEM-004T sensor"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='readings')
    
    # PZEM-004T Sensor Data
    voltage = models.DecimalField(max_digits=6, decimal_places=2, help_text="Voltage in V")
    current = models.DecimalField(max_digits=8, decimal_places=3, help_text="Current in A")
    power = models.DecimalField(max_digits=10, decimal_places=2, help_text="Active power in W")
    energy = models.DecimalField(max_digits=12, decimal_places=3, help_text="Energy consumption in kWh")
    frequency = models.DecimalField(max_digits=5, decimal_places=2, help_text="Frequency in Hz")
    power_factor = models.DecimalField(max_digits=4, decimal_places=3, help_text="Power factor (0-1)")
    
    # Timestamp
    timestamp = models.DateTimeField(db_index=True, help_text="Reading timestamp")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['device', '-timestamp']),
            models.Index(fields=['timestamp']),
        ]
        # Prevent duplicate readings for same device at exact same time
        unique_together = [['device', 'timestamp']]
    
    def __str__(self):
        return f"{self.device.name} - {self.timestamp} - {self.power}W"
    
    def calculate_cost(self, rate_per_kwh):
        """Calculate cost based on energy consumption and rate"""
        return float(self.energy) * float(rate_per_kwh)


class RateConfiguration(models.Model):
    """Electricity rate configuration in PHP (Philippine Peso)"""
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='rates')
    
    # Rate information
    rate_per_kwh = models.DecimalField(max_digits=8, decimal_places=4, help_text="Rate per kWh in PHP")
    name = models.CharField(max_length=100, help_text="Rate name (e.g., 'Peak Hours', 'Off-Peak')")
    description = models.TextField(blank=True, help_text="Rate description")
    
    # Time-based rate (optional)
    start_time = models.TimeField(null=True, blank=True, help_text="Start time for time-based rates")
    end_time = models.TimeField(null=True, blank=True, help_text="End time for time-based rates")
    
    # Status
    is_active = models.BooleanField(default=True, help_text="Active rate configuration")
    is_default = models.BooleanField(default=False, help_text="Default rate for device")
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-is_default', '-is_active', '-created_at']
        indexes = [
            models.Index(fields=['device', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.device.name} - {self.name} - ₱{self.rate_per_kwh}/kWh"
    
    def save(self, *args, **kwargs):
        # If this is set as default, unset other defaults for same device
        if self.is_default:
            RateConfiguration.objects.filter(
                device=self.device, 
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class FirmwareVersion(models.Model):
    """OTA Firmware versions for ESP8266"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Version information
    version = models.CharField(max_length=20, unique=True, help_text="Semantic version (e.g., 1.0.0)")
    description = models.TextField(help_text="Release notes and changes")
    
    # File
    firmware_file = models.FileField(upload_to='firmware/', help_text="Firmware binary file (.bin)")
    file_size = models.IntegerField(help_text="File size in bytes")
    checksum = models.CharField(max_length=64, help_text="MD5/SHA256 checksum for integrity")
    
    # Metadata
    is_stable = models.BooleanField(default=True, help_text="Stable release")
    is_latest = models.BooleanField(default=False, help_text="Latest version available")
    min_compatible_version = models.CharField(max_length=20, blank=True, help_text="Minimum compatible version for upgrade")
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['version']),
            models.Index(fields=['is_latest', 'is_stable']),
        ]
    
    def __str__(self):
        return f"v{self.version} {'(Latest)' if self.is_latest else ''}"
    
    def save(self, *args, **kwargs):
        # If this is set as latest, unset other latest versions
        if self.is_latest:
            FirmwareVersion.objects.filter(
                is_latest=True
            ).exclude(pk=self.pk).update(is_latest=False)
        super().save(*args, **kwargs)


class OTAUpdate(models.Model):
    """OTA Update tracking for devices"""
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('downloading', 'Downloading'),
        ('installing', 'Installing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(Device, on_delete=models.CASCADE, related_name='ota_updates')
    firmware_version = models.ForeignKey(FirmwareVersion, on_delete=models.CASCADE, related_name='updates')
    
    # Status
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    progress = models.IntegerField(default=0, help_text="Update progress percentage (0-100)")
    error_message = models.TextField(blank=True, help_text="Error details if failed")
    
    # Timing
    initiated_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True, help_text="When device started downloading")
    completed_at = models.DateTimeField(null=True, blank=True, help_text="When update completed")
    
    # Previous version
    previous_version = models.CharField(max_length=20, blank=True, help_text="Version before update")
    
    class Meta:
        ordering = ['-initiated_at']
        indexes = [
            models.Index(fields=['device', '-initiated_at']),
            models.Index(fields=['status']),
        ]
    
    def __str__(self):
        return f"{self.device.name} - {self.firmware_version.version} - {self.status}"
    
    def mark_started(self):
        """Mark update as started"""
        self.status = 'downloading'
        self.started_at = timezone.now()
        self.save()
    
    def mark_completed(self):
        """Mark update as completed"""
        self.status = 'completed'
        self.progress = 100
        self.completed_at = timezone.now()
        self.save()
    
    def mark_failed(self, error_message):
        """Mark update as failed"""
        self.status = 'failed'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()
