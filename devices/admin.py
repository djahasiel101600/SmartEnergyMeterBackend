from django.contrib import admin
from django.utils.html import format_html
from .models import Device, EnergyReading, RateConfiguration, FirmwareVersion, OTAUpdate


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'mac_address', 'status_badge', 'firmware_version', 'last_seen', 'created_at']
    list_filter = ['status', 'lcd_enabled', 'created_at']
    search_fields = ['name', 'mac_address', 'token']
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_seen']
    fieldsets = [
        ('Device Information', {
            'fields': ['id', 'name', 'token', 'mac_address']
        }),
        ('Status', {
            'fields': ['status', 'last_seen', 'firmware_version']
        }),
        ('LCD Configuration', {
            'fields': ['lcd_enabled', 'lcd_rotation_interval']
        }),
        ('Metadata', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def status_badge(self, obj):
        colors = {
            'online': 'green',
            'offline': 'gray',
            'error': 'red'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">●</span> {}',
            colors.get(obj.status, 'gray'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'


@admin.register(EnergyReading)
class EnergyReadingAdmin(admin.ModelAdmin):
    list_display = ['device', 'timestamp', 'voltage', 'current', 'power', 'energy', 'power_factor']
    list_filter = ['device', 'timestamp']
    search_fields = ['device__name', 'device__mac_address']
    readonly_fields = ['id', 'created_at']
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']
    
    fieldsets = [
        ('Reading Information', {
            'fields': ['id', 'device', 'timestamp']
        }),
        ('PZEM-004T Sensor Data', {
            'fields': ['voltage', 'current', 'power', 'energy', 'frequency', 'power_factor']
        }),
        ('Metadata', {
            'fields': ['created_at'],
            'classes': ['collapse']
        }),
    ]
    
    def has_add_permission(self, request):
        # Readings should only be added via WebSocket, not manually
        return False


@admin.register(RateConfiguration)
class RateConfigurationAdmin(admin.ModelAdmin):
    list_display = ['device', 'name', 'rate_per_kwh_display', 'is_default', 'is_active', 'time_range', 'created_at']
    list_filter = ['is_active', 'is_default', 'device']
    search_fields = ['name', 'description', 'device__name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = [
        ('Rate Information', {
            'fields': ['device', 'name', 'description', 'rate_per_kwh']
        }),
        ('Time-Based Rate (Optional)', {
            'fields': ['start_time', 'end_time'],
            'classes': ['collapse']
        }),
        ('Status', {
            'fields': ['is_active', 'is_default']
        }),
        ('Metadata', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def rate_per_kwh_display(self, obj):
        return f'₱{obj.rate_per_kwh}/kWh'
    rate_per_kwh_display.short_description = 'Rate'
    
    def time_range(self, obj):
        if obj.start_time and obj.end_time:
            return f'{obj.start_time.strftime("%H:%M")} - {obj.end_time.strftime("%H:%M")}'
        return '-'
    time_range.short_description = 'Time Range'


@admin.register(FirmwareVersion)
class FirmwareVersionAdmin(admin.ModelAdmin):
    list_display = ['version', 'is_latest_badge', 'is_stable_badge', 'file_size_display', 'created_at']
    list_filter = ['is_stable', 'is_latest', 'created_at']
    search_fields = ['version', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']
    
    fieldsets = [
        ('Version Information', {
            'fields': ['id', 'version', 'description']
        }),
        ('Firmware File', {
            'fields': ['firmware_file', 'file_size', 'checksum']
        }),
        ('Release Information', {
            'fields': ['is_stable', 'is_latest', 'min_compatible_version']
        }),
        ('Metadata', {
            'fields': ['created_at', 'updated_at'],
            'classes': ['collapse']
        }),
    ]
    
    def is_latest_badge(self, obj):
        if obj.is_latest:
            return format_html('<span style="color: green; font-weight: bold;">✓ Latest</span>')
        return '-'
    is_latest_badge.short_description = 'Latest'
    
    def is_stable_badge(self, obj):
        if obj.is_stable:
            return format_html('<span style="color: blue;">✓ Stable</span>')
        return format_html('<span style="color: orange;">⚠ Beta</span>')
    is_stable_badge.short_description = 'Stability'
    
    def file_size_display(self, obj):
        size_kb = obj.file_size / 1024
        if size_kb < 1024:
            return f'{size_kb:.2f} KB'
        return f'{size_kb / 1024:.2f} MB'
    file_size_display.short_description = 'File Size'


@admin.register(OTAUpdate)
class OTAUpdateAdmin(admin.ModelAdmin):
    list_display = ['device', 'firmware_version', 'status_badge', 'progress_bar', 'initiated_at', 'completed_at']
    list_filter = ['status', 'device', 'initiated_at']
    search_fields = ['device__name', 'firmware_version__version', 'error_message']
    readonly_fields = ['id', 'initiated_at', 'started_at', 'completed_at', 'previous_version']
    date_hierarchy = 'initiated_at'
    ordering = ['-initiated_at']
    
    fieldsets = [
        ('Update Information', {
            'fields': ['id', 'device', 'firmware_version', 'previous_version']
        }),
        ('Status', {
            'fields': ['status', 'progress', 'error_message']
        }),
        ('Timing', {
            'fields': ['initiated_at', 'started_at', 'completed_at']
        }),
    ]
    
    def status_badge(self, obj):
        colors = {
            'pending': 'gray',
            'downloading': 'blue',
            'installing': 'orange',
            'completed': 'green',
            'failed': 'red',
            'cancelled': 'gray'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">●</span> {}',
            colors.get(obj.status, 'gray'),
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def progress_bar(self, obj):
        if obj.status in ['completed']:
            color = 'green'
        elif obj.status == 'failed':
            color = 'red'
        else:
            color = 'blue'
        
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 20px; border-radius: 3px; text-align: center; color: white; font-size: 12px; line-height: 20px;">{}%</div>'
            '</div>',
            obj.progress, color, obj.progress
        )
    progress_bar.short_description = 'Progress'
