# TWF Weather Models Frontend - Enhanced Version

## Overview
This is the enhanced frontend for The Weather Forums weather model viewer, featuring a modern weather app design with improved usability and functionality.

## New Features

### 1. **Dropdown Selectors**
- **Variable Dropdown**: Select any available weather variable from a dropdown menu
- **Forecast Hour Dropdown**: Select specific forecast hours
- Both dropdowns automatically populate based on available data from the API
- Future variables and forecast hours are automatically detected and added

### 2. **Animation Slider**
- **Time Slider**: Scrub through forecast hours manually
- **Play/Pause Controls**: Animate through all available forecast hours
- **Adjustable Speed**: Control animation speed from 0.5 to 4 frames per second (default: 2 fps)
- Smooth animations with image preloading

### 3. **Modern Weather App Design**
- **Color Scheme**: Professional blues and grays palette
- **Dark Theme**: Easy on the eyes for extended viewing
- **The Weather Forums Branding**: Prominent in header
- **Clean Layout**: Controls on sidebar, map takes center stage, metadata in footer

### 4. **Mobile-Friendly & Responsive**
- **Portrait Optimization**: Designed for mobile portrait viewing
- **Adaptive Layout**: Sidebar moves to top on mobile devices
- **Touch-Friendly Controls**: Large touch targets for mobile interaction
- **Scalable Design**: Works on all screen sizes from phone to desktop

### 5. **Enhanced User Experience**
- **Loading Spinner**: Visual feedback while maps load
- **Error Messages**: Clear error notifications
- **Image Preloading**: Smooth animation playback
- **Smart Caching**: Reduces redundant API calls
- **Metadata Display**: Shows variable, forecast time, valid time, and region

## Technical Details

### File Structure
```
frontend/models/
├── index.html          # Main HTML structure
├── config.js           # Configuration (API endpoint, variables, etc.)
├── css/
│   └── style.css      # Modern weather app styling
└── js/
    ├── api-client.js  # API communication layer
    └── map-viewer.js  # Main application logic
```

### Browser Compatibility
- Modern browsers (Chrome, Firefox, Safari, Edge)
- Mobile browsers (iOS Safari, Chrome Mobile)
- Responsive design for screens 320px and up

### Performance Features
- Image caching for smoother navigation
- Preloading of adjacent forecast hours
- Efficient API calls with filtering
- Auto-refresh every minute for new data

## Configuration

### Adding New Variables
Variables are automatically detected from the API. To add display names, edit `config.js`:

```javascript
VARIABLES: {
    'new_variable': {
        label: 'Display Name',
        units: 'units',
        description: 'Full description'
    }
}
```

### Adjusting Forecast Hours
Forecast hours are automatically detected from available maps. No configuration needed!

### Changing API Endpoint
Edit `config.js` and update `API_BASE_URL`:

```javascript
const CONFIG = {
    API_BASE_URL: 'https://your-new-domain.com',
    // ...
};
```

## Usage

### For Users
1. **Select a Variable**: Choose from the dropdown (Temperature, Precipitation, etc.)
2. **Select Forecast Hour**: Pick a specific time or use the slider
3. **Animate**: Click Play to see the forecast evolve over time
4. **Adjust Speed**: Use the speed slider to control animation pace

### For Developers
The viewer automatically:
- Detects available variables from the API
- Detects available forecast hours
- Preloads images for smooth animation
- Updates when new data becomes available

## Mobile Experience
On mobile devices:
- Controls move to top of screen
- Map fills majority of viewport
- Portrait orientation prioritized
- Touch-optimized sliders and buttons
- Metadata stacks vertically for readability

## Future Enhancements
Potential additions for future versions:
- Side-by-side map comparison
- Custom regions/zoom levels
- Download map functionality
- Permalink sharing for specific forecasts
- Full-screen mode
- Favorite variables/presets

## Support
For issues or questions, visit [The Weather Forums](https://theweatherforums.com)
