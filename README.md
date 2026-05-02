# Smart Energy Meter Backend

Django backend for the Smart Energy Meter system with REST API and WebSocket support.

## Features

- RESTful API for device management and data access
- WebSocket support for real-time communication with ESP8266 devices and frontend
- Multi-device support
- Advanced analytics and insights
- OTA firmware update management
- PostgreSQL support for production

## Setup

### Prerequisites

- Python 3.10 or higher
- Redis (for WebSocket channel layer)
- PostgreSQL (for production)

### Installation

1. Create and activate virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create `.env` file from example:

```powershell
Copy-Item .env.example .env
```

4. Edit `.env` and configure your settings (database, Redis, etc.)

5. Run migrations:

```powershell
python manage.py migrate
```

6. Create superuser:

```powershell
python manage.py createsuperuser
```

7. Run development server:

```powershell
# For HTTP only
python manage.py runserver

# For WebSocket support (recommended)
daphne -b 0.0.0.0 -p 8000 backend.asgi:application
```

## API Endpoints

### REST API

- `GET /api/devices/` - List all devices
- `POST /api/devices/` - Register new device
- `GET /api/devices/{id}/` - Get device details
- `PUT /api/devices/{id}/` - Update device
- `DELETE /api/devices/{id}/` - Delete device

- `GET /api/readings/` - List energy readings (with filters)
- `GET /api/readings/aggregated/` - Get aggregated data

- `GET /api/rates/` - List kWh rates
- `POST /api/rates/` - Create new rate
- `GET /api/rates/current/` - Get current active rate

- `GET /api/firmware/` - List firmware versions
- `POST /api/firmware/upload/` - Upload new firmware
- `POST /api/ota/schedule/` - Schedule OTA update
- `POST /api/ota/{id}/rollback/` - Rollback OTA update

- `GET /api/analytics/cost-projection/` - Cost projections
- `GET /api/analytics/usage-patterns/` - Usage patterns
- `GET /api/analytics/comparisons/` - Comparison charts
- `GET /api/analytics/anomalies/` - Detected anomalies
- `GET /api/analytics/appliances/` - Appliance detection

### WebSocket Endpoints

#### Device Connection (ESP8266)

```
ws://backend/ws/device/<device_token>/
```

**Messages from Device:**

```json
{
  "type": "energy_data",
  "voltage": 230.5,
  "current": 2.3,
  "power": 530,
  "energy": 12.5,
  "frequency": 50.0,
  "pf": 0.95,
  "timestamp": 1714567890
}
```

**Messages to Device:**

```json
{
  "action": "lcd_config",
  "line1": "Power: {power}W",
  "line2": "Cost: {cost}PHP"
}

{
  "action": "reset"
}

{
  "action": "ota",
  "firmware_url": "https://backend.com/media/firmware/v2.0.0.bin"
}
```

#### Frontend Connection

```
ws://backend/ws/energy/
```

**Messages from Backend:**

```json
{
  "type": "energy_update",
  "device_id": 1,
  "data": {
    "voltage": 230.5,
    "current": 2.3,
    "power": 530,
    ...
  }
}

{
  "type": "device_status",
  "device_id": 1,
  "status": "online"
}

{
  "type": "notification",
  "message": "Device 1 OTA update completed"
}
```

## Database Configuration

### Development (SQLite)

No configuration needed. SQLite database will be created automatically.

### Production (PostgreSQL)

Set `DATABASE_URL` in `.env`:

```
DATABASE_URL=postgresql://user:password@host:port/dbname
```

## Redis Configuration

### Local Development

Install and run Redis:

```powershell
# Using Windows Subsystem for Linux (WSL)
wsl
sudo service redis-server start

# Or use Docker
docker run -p 6379:6379 redis
```

Set in `.env`:

```
REDIS_URL=redis://localhost:6379/0
```

### Production (Render/Upstash)

Use managed Redis service and set `REDIS_URL` accordingly.

## Deployment

See deployment guide in root README.md for Render deployment instructions.

## Project Structure

```
backend/
├── backend/              # Django project settings
│   ├── settings.py       # Main settings
│   ├── asgi.py          # ASGI config for WebSocket
│   ├── routing.py       # WebSocket URL routing
│   ├── urls.py          # HTTP URL routing
│   └── wsgi.py          # WSGI config
├── devices/             # Main Django app
│   ├── models.py        # Database models
│   ├── serializers.py   # DRF serializers
│   ├── views.py         # API views
│   ├── consumers.py     # WebSocket consumers
│   ├── analytics.py     # Analytics utilities
│   └── admin.py         # Django admin config
├── manage.py
├── requirements.txt
└── .env
```

## License

MIT
