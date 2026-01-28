/**
 * TWF Models Configuration
 * 
 * To migrate to a different domain, only change the API_BASE_URL below.
 */

const CONFIG = {
    // API endpoint - change this when moving to theweatherforums.com
    API_BASE_URL: 'https://api.sodakweather.com',
    
    // Available variables (UI metadata - labels, units, descriptions)
    // Model capabilities (excluded variables) come from API
    VARIABLES: {
        'temp': {
            label: 'Temperature',
            units: '°F',
            description: '2m Temperature',
        },
        'precip': {
            label: 'Total Precip',
            units: 'inches',
            description: 'Total Precipitation',
        },
        'wind_speed': {
            label: 'Wind Speed',
            units: 'mph',
            description: '10m Wind Speed',
        },
        'mslp_precip': {
            label: 'MSLP & Precip',
            units: 'mb / inches',
            description: 'Mean Sea Level Pressure & Precipitation',
        },
        'temp_850_wind_mslp': {
            label: '850mb Analysis',
            units: '°C / mph / mb',
            description: '850mb Temperature, Wind, and MSLP',
        },
        'radar': {
            label: 'Radar',
            units: 'dBZ',
            description: 'Simulated Composite Radar Reflectivity',
        }
    },
    
    // Default selections (will be validated against API)
    DEFAULT_MODEL: 'GFS',
    DEFAULT_VARIABLE: 'temp',
    DEFAULT_FORECAST_HOUR: 0,
    
    // Forecast hours (6-hour increments for smooth temporal resolution)
    FORECAST_HOURS: [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72],
    
    // UI settings
    REFRESH_INTERVAL: 60000, // 1 minute
    ANIMATION_SPEED: 2, // frames per second
    PRELOAD_COUNT: 3, // Preload next N images
    
    // Region
    REGION: 'Pacific Northwest',
    
    // Models loaded dynamically from API
    MODELS: null,  // Populated by APIClient.getModels()
    
    // Cache duration for model metadata (milliseconds)
    MODEL_CACHE_DURATION: 300000, // 5 minutes
};
