# API Documentation

## Base URL
```
https://api.sodakweather.com
```

## Endpoints

### Get Available Models
```
GET /api/models
```

Returns list of all enabled weather models and their capabilities.

**Response:**
```json
{
  "models": [
    {
      "id": "GFS",
      "name": "GFS",
      "full_name": "Global Forecast System",
      "description": "NOAA's global weather model",
      "resolution": "0.25",
      "max_forecast_hour": 384,
      "forecast_increment": 6,
      "run_hours": [0, 6, 12, 18],
      "excluded_variables": [],
      "color": "#1E90FF",
      "enabled": true
    },
    {
      "id": "AIGFS",
      "name": "AIGFS",
      "full_name": "Artificial Intelligence Global Forecast System",
      "description": "NOAA's AI-enhanced global forecast model",
      "resolution": "0.25",
      "max_forecast_hour": 384,
      "forecast_increment": 6,
      "run_hours": [0, 6, 12, 18],
      "excluded_variables": ["radar"],
      "color": "#4169E1",
      "enabled": true
    }
  ]
}
```

### Get Model Information
```
GET /api/models/{model_id}
```

Returns detailed information about a specific model.

**Path Parameters:**
- `model_id`: Model identifier (e.g., "GFS", "AIGFS")

**Response:**
```json
{
  "id": "GFS",
  "name": "GFS",
  "full_name": "Global Forecast System",
  "description": "NOAA's global weather model",
  "resolution": "0.25",
  "max_forecast_hour": 384,
  "forecast_increment": 6,
  "run_hours": [0, 6, 12, 18],
  "excluded_variables": [],
  "color": "#1E90FF",
  "enabled": true,
  "provider": "NOMADS",
  "has_refc": true,
  "has_upper_air": true
}
```

**Error Responses:**
- `404`: Model not found
- `403`: Model exists but is not enabled

### Get Available Maps
```
GET /api/maps
```

Returns list of available forecast maps with metadata.

**Query Parameters:**
- `model` (optional): Filter by model (e.g., "GFS", "AIGFS")
- `variable` (optional): Filter by variable
- `forecast_hour` (optional): Filter by forecast hour
- `run_time` (optional): Filter by run time (ISO format: 2026-01-24T00:00:00Z)

**Example Requests:**
```
GET /api/maps                           # All maps from all models
GET /api/maps?model=GFS                 # Only GFS maps
GET /api/maps?model=GFS&variable=temp   # GFS temperature maps
GET /api/maps?model=AIGFS&forecast_hour=12  # AIGFS 12-hour maps
```

**Response:**
```json
{
  "maps": [
    {
      "id": "gfs_20250123_00_temp_2m",
      "model": "GFS",
      "run_time": "2025-01-23T00:00:00Z",
      "forecast_hour": 0,
      "variable": "temperature_2m",
      "image_url": "/api/images/gfs_20250123_00_temp_2m.png",
      "created_at": "2025-01-23T01:15:00Z"
    }
  ]
}
```

### Get Map Image
```
GET /api/images/{map_id}.png
```

Returns the map image file.

**Query Parameters:**
- `width` (optional): Image width in pixels
- `height` (optional): Image height in pixels

### Get Map Metadata
```
GET /api/maps/{map_id}
```

Returns detailed metadata for a specific map.

**Response:**
```json
{
  "id": "gfs_20250123_00_temp_2m",
  "model": "GFS",
  "run_time": "2025-01-23T00:00:00Z",
  "forecast_hour": 0,
  "variable": "temperature_2m",
  "units": "Celsius",
  "valid_time": "2025-01-23T00:00:00Z",
  "image_url": "/api/images/gfs_20250123_00_temp_2m.png",
  "file_size": 245678,
  "dimensions": {
    "width": 1920,
    "height": 1080
  }
}
```

### Trigger Manual Update
```
POST /api/update
```

Manually trigger a data fetch and map generation (admin only).

**Response:**
```json
{
  "status": "started",
  "job_id": "update_20250123_001500"
}
```

## Variables Supported

- `temperature_2m`: 2-meter temperature
- `precipitation`: Total precipitation
- `wind_speed_10m`: 10-meter wind speed
- `wind_direction_10m`: 10-meter wind direction
- `pressure_surface`: Surface pressure
- `relative_humidity_2m`: 2-meter relative humidity
- `cloud_cover`: Cloud cover percentage

## Forecast Hours

Standard forecast hours: 0, 6, 12, 18, 24, 48, 72, 96, 120
