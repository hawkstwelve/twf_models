/**
 * TWF Models Configuration
 * 
 * To migrate to a different domain, only change the API_BASE_URL below.
 */

const CONFIG = {
    // API endpoint - change this when moving to theweatherforums.com
    API_BASE_URL: 'https://api.sodakweather.com',
    
    // Available variables
    VARIABLES: {
        'temp': {
            label: 'Temperature',
            units: '°F',
            description: '2m Temperature'
        },
        'precip': {
            label: 'Total Precip',
            units: 'inches',
            description: 'Total Precipitation'
        },
        'wind_speed': {
            label: 'Wind Speed',
            units: 'mph',
            description: '10m Wind Speed'
        },
        'mslp_precip': {
            label: 'MSLP & Precip',
            units: 'mb / inches',
            description: 'Mean Sea Level Pressure & Precipitation'
        },
        'temp_850_wind_mslp': {
            label: '850mb Temp',
            units: '°C / mph / mb',
            description: '850mb Temperature, Wind, and MSLP'
        }
    },
    
    // Forecast hours
    FORECAST_HOURS: [0, 24, 48, 72],
    
    // Refresh interval when waiting for new maps (milliseconds)
    REFRESH_INTERVAL: 60000, // 1 minute
    
    // Region
    REGION: 'Pacific Northwest'
};
