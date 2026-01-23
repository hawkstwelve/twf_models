# Current Project Configuration

## Summary of Settings

Based on your requirements, here's what's currently configured:

### Weather Variables
- ✅ **Temperature (2m)** - Fahrenheit
- ✅ **Precipitation Type** - Rain/Snow/Freezing Rain map (radar-like)
- ✅ **Total Precipitation** - Inches
- ✅ **Wind Speed (10m)** - MPH
- ⏸️ **Wind Gusts** - To be added later

### Region Focus
- **Pacific Northwest (PNW)**
  - Washington (WA)
  - Oregon (OR)
  - Idaho (ID)
  - Boundaries: -125° to -110° longitude, 42° to 49° latitude
  - Map projection: Lambert Conformal optimized for PNW

### Forecast Hours
- **Initial**: 0, 24, 48, 72 hours
- Can expand to more hours once system is confirmed working

### Units
- **Temperature**: Fahrenheit (°F)
- **Precipitation**: Inches (in)
- **Wind Speed**: Miles per hour (mph)

### Update Schedule
- Every 6 hours (aligned with GFS model runs at 00, 06, 12, 18 UTC)

### Integration
- **Platform**: Invision Community v4 (upgrading to v5)
- **Location**: `/models` page in navigation
- **Status**: Coming soon page until ready
- **Forum Hosting**: Digital Ocean droplet

### Deployment
- **Recommended**: Separate Digital Ocean droplet ($12-24/month)
- **Alternative**: Same droplet as forums (cost saving, but may impact performance)

## Next Steps

1. ✅ Configuration complete
2. ⏳ Test data fetching
3. ⏳ Generate first test maps
4. ⏳ Deploy to droplet
5. ⏳ Set up scheduled processing
6. ⏳ Create coming soon page in Invision
7. ⏳ Test integration
8. ⏳ Public release

## Notes

- Wind gusts feature removed from initial release (can add later)
- Forecast hours limited to key times initially
- All units set to US standard (Fahrenheit, inches, mph)
- PNW region boundaries configured
- Coming soon page template created
