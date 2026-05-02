"""
Analytics utilities for energy consumption analysis.
Includes cost projections, usage patterns, comparisons, anomaly detection, and appliance detection.
"""

from django.db.models import Sum, Avg, Max, Min, Count, Q, F
from django.utils import timezone
from datetime import timedelta, datetime, time
from decimal import Decimal
import statistics
from typing import List, Dict, Tuple, Optional
import logging

from .models import Device, EnergyReading, RateConfiguration

logger = logging.getLogger(__name__)


class CostProjectionAnalyzer:
    """Analyze and project energy costs"""
    
    @staticmethod
    def project_daily_cost(device: Device, hours: int = 24) -> Dict:
        """
        Project daily cost based on recent consumption
        
        Args:
            device: Device to analyze
            hours: Number of hours to use for projection (default: 24)
        
        Returns:
            Dict with projected daily, weekly, and monthly costs
        """
        start_time = timezone.now() - timedelta(hours=hours)
        readings = device.readings.filter(timestamp__gte=start_time).order_by('timestamp')
        
        if not readings.exists():
            return {
                'daily': 0,
                'weekly': 0,
                'monthly': 0,
                'currency': 'PHP',
                'confidence': 'low',
                'message': 'Insufficient data'
            }
        
        # Get default rate
        rate = device.rates.filter(is_default=True, is_active=True).first()
        if not rate:
            return {
                'daily': 0,
                'weekly': 0,
                'monthly': 0,
                'currency': 'PHP',
                'confidence': 'low',
                'message': 'No rate configured'
            }
        
        # Calculate energy consumption in the period
        first_reading = readings.first()
        last_reading = readings.last()
        
        energy_consumed = float(last_reading.energy) - float(first_reading.energy)
        time_diff_hours = (last_reading.timestamp - first_reading.timestamp).total_seconds() / 3600
        
        if time_diff_hours <= 0:
            return {
                'daily': 0,
                'weekly': 0,
                'monthly': 0,
                'currency': 'PHP',
                'confidence': 'low',
                'message': 'Invalid time range'
            }
        
        # Calculate hourly consumption rate
        hourly_consumption = energy_consumed / time_diff_hours
        
        # Project costs
        daily_kwh = hourly_consumption * 24
        weekly_kwh = daily_kwh * 7
        monthly_kwh = daily_kwh * 30
        
        rate_value = float(rate.rate_per_kwh)
        
        # Determine confidence based on data points
        reading_count = readings.count()
        if reading_count >= 1000:  # ~8 hours at 2-3s intervals
            confidence = 'high'
        elif reading_count >= 500:
            confidence = 'medium'
        else:
            confidence = 'low'
        
        return {
            'daily': round(daily_kwh * rate_value, 2),
            'weekly': round(weekly_kwh * rate_value, 2),
            'monthly': round(monthly_kwh * rate_value, 2),
            'currency': 'PHP',
            'confidence': confidence,
            'hourly_kwh': round(hourly_consumption, 4),
            'daily_kwh': round(daily_kwh, 4),
            'rate_per_kwh': rate_value,
            'data_points': reading_count,
            'period_hours': round(time_diff_hours, 2)
        }
    
    @staticmethod
    def compare_periods(device: Device, period1_start: datetime, period1_end: datetime,
                       period2_start: datetime, period2_end: datetime) -> Dict:
        """
        Compare energy consumption between two periods
        
        Returns:
            Dict with comparison metrics and percentage changes
        """
        # Get readings for both periods
        period1_readings = device.readings.filter(
            timestamp__gte=period1_start,
            timestamp__lte=period1_end
        )
        
        period2_readings = device.readings.filter(
            timestamp__gte=period2_start,
            timestamp__lte=period2_end
        )
        
        def calculate_period_stats(readings):
            if not readings.exists():
                return None
            
            first = readings.first()
            last = readings.last()
            
            energy = float(last.energy) - float(first.energy) if last and first else 0
            
            stats = readings.aggregate(
                avg_power=Avg('power'),
                max_power=Max('power'),
                min_power=Min('power'),
                avg_voltage=Avg('voltage'),
                avg_current=Avg('current')
            )
            
            return {
                'energy_kwh': energy,
                'avg_power': float(stats['avg_power'] or 0),
                'max_power': float(stats['max_power'] or 0),
                'min_power': float(stats['min_power'] or 0),
                'avg_voltage': float(stats['avg_voltage'] or 0),
                'avg_current': float(stats['avg_current'] or 0),
                'reading_count': readings.count()
            }
        
        period1_stats = calculate_period_stats(period1_readings)
        period2_stats = calculate_period_stats(period2_readings)
        
        if not period1_stats or not period2_stats:
            return {
                'error': 'Insufficient data for comparison',
                'period1': period1_stats,
                'period2': period2_stats
            }
        
        # Calculate percentage changes
        def pct_change(old, new):
            if old == 0:
                return 0
            return ((new - old) / old) * 100
        
        return {
            'period1': {
                'start': period1_start.isoformat(),
                'end': period1_end.isoformat(),
                **period1_stats
            },
            'period2': {
                'start': period2_start.isoformat(),
                'end': period2_end.isoformat(),
                **period2_stats
            },
            'changes': {
                'energy_pct': round(pct_change(period1_stats['energy_kwh'], period2_stats['energy_kwh']), 2),
                'avg_power_pct': round(pct_change(period1_stats['avg_power'], period2_stats['avg_power']), 2),
                'max_power_pct': round(pct_change(period1_stats['max_power'], period2_stats['max_power']), 2),
            },
            'verdict': 'increased' if period2_stats['energy_kwh'] > period1_stats['energy_kwh'] else 'decreased'
        }


class UsagePatternAnalyzer:
    """Analyze usage patterns and identify trends"""
    
    @staticmethod
    def analyze_hourly_pattern(device: Device, days: int = 7) -> Dict:
        """
        Analyze hourly usage patterns over specified days
        
        Returns:
            Dict with average power consumption per hour of day
        """
        start_time = timezone.now() - timedelta(days=days)
        readings = device.readings.filter(timestamp__gte=start_time)
        
        if not readings.exists():
            return {'error': 'Insufficient data'}
        
        # Group by hour of day (0-23)
        hourly_data = {}
        for hour in range(24):
            hourly_data[hour] = []
        
        for reading in readings.iterator():
            hour = reading.timestamp.hour
            hourly_data[hour].append(float(reading.power))
        
        # Calculate average for each hour
        hourly_averages = {}
        for hour, powers in hourly_data.items():
            if powers:
                hourly_averages[hour] = {
                    'avg_power': round(statistics.mean(powers), 2),
                    'max_power': round(max(powers), 2),
                    'min_power': round(min(powers), 2),
                    'sample_count': len(powers)
                }
            else:
                hourly_averages[hour] = {
                    'avg_power': 0,
                    'max_power': 0,
                    'min_power': 0,
                    'sample_count': 0
                }
        
        # Identify peak hours
        peak_hours = sorted(
            [(h, d['avg_power']) for h, d in hourly_averages.items()],
            key=lambda x: x[1],
            reverse=True
        )[:3]
        
        # Identify low usage hours
        low_hours = sorted(
            [(h, d['avg_power']) for h, d in hourly_averages.items()],
            key=lambda x: x[1]
        )[:3]
        
        return {
            'hourly_averages': hourly_averages,
            'peak_hours': [{'hour': h, 'avg_power': p} for h, p in peak_hours],
            'low_hours': [{'hour': h, 'avg_power': p} for h, p in low_hours],
            'analysis_period_days': days
        }
    
    @staticmethod
    def analyze_daily_pattern(device: Device, days: int = 30) -> Dict:
        """
        Analyze daily usage patterns
        
        Returns:
            Dict with daily consumption statistics
        """
        start_time = timezone.now() - timedelta(days=days)
        
        daily_data = []
        
        for day in range(days):
            day_start = start_time + timedelta(days=day)
            day_end = day_start + timedelta(days=1)
            
            day_readings = device.readings.filter(
                timestamp__gte=day_start,
                timestamp__lt=day_end
            )
            
            if day_readings.exists():
                first = day_readings.first()
                last = day_readings.last()
                energy = float(last.energy) - float(first.energy)
                
                stats = day_readings.aggregate(
                    avg_power=Avg('power'),
                    max_power=Max('power')
                )
                
                daily_data.append({
                    'date': day_start.date().isoformat(),
                    'energy_kwh': round(energy, 4),
                    'avg_power': round(float(stats['avg_power'] or 0), 2),
                    'max_power': round(float(stats['max_power'] or 0), 2),
                    'day_of_week': day_start.strftime('%A')
                })
        
        if not daily_data:
            return {'error': 'Insufficient data'}
        
        # Calculate averages
        avg_daily_energy = statistics.mean([d['energy_kwh'] for d in daily_data])
        
        # Group by day of week
        weekday_data = {}
        for day_stat in daily_data:
            dow = day_stat['day_of_week']
            if dow not in weekday_data:
                weekday_data[dow] = []
            weekday_data[dow].append(day_stat['energy_kwh'])
        
        weekday_averages = {
            dow: round(statistics.mean(energies), 4)
            for dow, energies in weekday_data.items()
        }
        
        return {
            'daily_data': daily_data,
            'avg_daily_energy': round(avg_daily_energy, 4),
            'weekday_averages': weekday_averages,
            'highest_day': max(daily_data, key=lambda x: x['energy_kwh']),
            'lowest_day': min(daily_data, key=lambda x: x['energy_kwh'])
        }


class AnomalyDetector:
    """Detect anomalies in energy consumption"""
    
    @staticmethod
    def detect_power_spikes(device: Device, hours: int = 24, threshold_multiplier: float = 2.0) -> List[Dict]:
        """
        Detect unusual power spikes
        
        Args:
            device: Device to analyze
            hours: Period to analyze
            threshold_multiplier: Multiplier for average to detect spikes
        
        Returns:
            List of detected anomalies
        """
        start_time = timezone.now() - timedelta(hours=hours)
        readings = device.readings.filter(timestamp__gte=start_time)
        
        if readings.count() < 100:
            return []
        
        # Calculate average and standard deviation
        stats = readings.aggregate(
            avg_power=Avg('power'),
            max_power=Max('power')
        )
        
        avg_power = float(stats['avg_power'] or 0)
        threshold = avg_power * threshold_multiplier
        
        # Find spikes
        spikes = readings.filter(power__gt=threshold).order_by('-power')[:10]
        
        anomalies = []
        for spike in spikes:
            anomalies.append({
                'timestamp': spike.timestamp.isoformat(),
                'power': float(spike.power),
                'voltage': float(spike.voltage),
                'current': float(spike.current),
                'deviation_pct': round(((float(spike.power) - avg_power) / avg_power) * 100, 2),
                'severity': 'high' if float(spike.power) > threshold * 1.5 else 'medium'
            })
        
        return anomalies
    
    @staticmethod
    def detect_unusual_consumption(device: Device, current_period_hours: int = 24,
                                  comparison_days: int = 7) -> Dict:
        """
        Detect unusual consumption compared to historical average
        
        Returns:
            Dict with anomaly assessment
        """
        # Current period
        current_start = timezone.now() - timedelta(hours=current_period_hours)
        current_readings = device.readings.filter(timestamp__gte=current_start)
        
        # Historical period
        historical_end = current_start
        historical_start = historical_end - timedelta(days=comparison_days)
        historical_readings = device.readings.filter(
            timestamp__gte=historical_start,
            timestamp__lt=historical_end
        )
        
        if not current_readings.exists() or not historical_readings.exists():
            return {'error': 'Insufficient data'}
        
        # Calculate current consumption
        current_first = current_readings.first()
        current_last = current_readings.last()
        current_energy = float(current_last.energy) - float(current_first.energy)
        current_hours = (current_last.timestamp - current_first.timestamp).total_seconds() / 3600
        current_rate = current_energy / current_hours if current_hours > 0 else 0
        
        # Calculate historical average
        historical_first = historical_readings.first()
        historical_last = historical_readings.last()
        historical_energy = float(historical_last.energy) - float(historical_first.energy)
        historical_hours = (historical_last.timestamp - historical_first.timestamp).total_seconds() / 3600
        historical_rate = historical_energy / historical_hours if historical_hours > 0 else 0
        
        if historical_rate == 0:
            return {'error': 'Invalid historical data'}
        
        # Calculate deviation
        deviation_pct = ((current_rate - historical_rate) / historical_rate) * 100
        
        # Determine if anomalous
        is_anomalous = abs(deviation_pct) > 30  # 30% deviation threshold
        
        severity = 'normal'
        if abs(deviation_pct) > 50:
            severity = 'high'
        elif abs(deviation_pct) > 30:
            severity = 'medium'
        
        return {
            'is_anomalous': is_anomalous,
            'severity': severity,
            'current_rate_kwh_per_hour': round(current_rate, 4),
            'historical_rate_kwh_per_hour': round(historical_rate, 4),
            'deviation_pct': round(deviation_pct, 2),
            'message': f'Consumption is {"higher" if deviation_pct > 0 else "lower"} than usual by {abs(round(deviation_pct, 1))}%'
        }


class ApplianceDetector:
    """Detect appliance usage based on power consumption patterns"""
    
    # Common appliance power ranges (in Watts)
    APPLIANCE_SIGNATURES = {
        'LED Bulb': (5, 20),
        'CFL Bulb': (13, 30),
        'Incandescent Bulb': (40, 100),
        'Laptop': (30, 90),
        'Desktop Computer': (100, 400),
        'Monitor': (20, 60),
        'TV (LED)': (50, 150),
        'TV (Plasma)': (150, 400),
        'Refrigerator': (100, 250),
        'Microwave': (600, 1200),
        'Electric Kettle': (1200, 3000),
        'Rice Cooker': (300, 700),
        'Electric Fan': (50, 100),
        'Aircon (0.5HP)': (400, 600),
        'Aircon (1.0HP)': (750, 1000),
        'Aircon (1.5HP)': (1100, 1400),
        'Aircon (2.0HP)': (1500, 2000),
        'Washing Machine': (350, 500),
        'Electric Iron': (800, 1800),
        'Hair Dryer': (800, 1800),
        'Water Heater': (1500, 3000),
        'Oven': (2000, 5000),
    }
    
    @staticmethod
    def detect_appliances(device: Device, hours: int = 1) -> List[Dict]:
        """
        Detect likely appliances based on current power consumption
        
        Args:
            device: Device to analyze
            hours: Recent period to analyze
        
        Returns:
            List of likely appliances
        """
        start_time = timezone.now() - timedelta(hours=hours)
        readings = device.readings.filter(timestamp__gte=start_time)
        
        if not readings.exists():
            return []
        
        # Get recent average power
        avg_power = readings.aggregate(avg=Avg('power'))['avg']
        current_power = float(avg_power or 0)
        
        # Find matching appliances
        matches = []
        for appliance, (min_power, max_power) in ApplianceDetector.APPLIANCE_SIGNATURES.items():
            if min_power <= current_power <= max_power:
                # Calculate confidence based on how well it fits
                mid_range = (min_power + max_power) / 2
                deviation = abs(current_power - mid_range) / mid_range
                confidence = max(0, 100 - (deviation * 100))
                
                matches.append({
                    'appliance': appliance,
                    'confidence': round(confidence, 1),
                    'power_range': f'{min_power}-{max_power}W',
                    'current_power': round(current_power, 2)
                })
        
        # Sort by confidence
        matches.sort(key=lambda x: x['confidence'], reverse=True)
        
        return matches[:5]  # Return top 5 matches
    
    @staticmethod
    def detect_power_state_changes(device: Device, hours: int = 24, threshold: float = 50.0) -> List[Dict]:
        """
        Detect significant power state changes (appliance on/off events)
        
        Args:
            device: Device to analyze
            hours: Period to analyze
            threshold: Minimum power change to detect (Watts)
        
        Returns:
            List of detected state changes
        """
        start_time = timezone.now() - timedelta(hours=hours)
        readings = list(device.readings.filter(timestamp__gte=start_time).order_by('timestamp'))
        
        if len(readings) < 10:
            return []
        
        events = []
        
        # Use sliding window to detect changes
        window_size = 5
        for i in range(window_size, len(readings) - window_size):
            before_avg = statistics.mean([float(readings[j].power) for j in range(i - window_size, i)])
            after_avg = statistics.mean([float(readings[j].power) for j in range(i, i + window_size)])
            
            power_change = after_avg - before_avg
            
            if abs(power_change) >= threshold:
                event_type = 'device_on' if power_change > 0 else 'device_off'
                
                events.append({
                    'timestamp': readings[i].timestamp.isoformat(),
                    'event_type': event_type,
                    'power_change': round(power_change, 2),
                    'power_before': round(before_avg, 2),
                    'power_after': round(after_avg, 2),
                })
        
        # Limit to most significant events
        events.sort(key=lambda x: abs(x['power_change']), reverse=True)
        return events[:20]
