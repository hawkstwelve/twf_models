# API Documentation

## Endpoints

### Get Available Maps
```
GET /api/maps
```

Returns list of available forecast maps with metadata.

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
