# MSLP & Precip Map Colorbar Fix

## Issue
The MSLP & Precipitation maps were only showing a single colorbar (either blue for snow, green for rain, or pink for freezing rain), depending on which precipitation type was last processed. All colorbars for different precipitation types should be displayed on every map.

## Root Cause
The code was overwriting the `im` variable with each precipitation type in a loop, so only the last precipitation type that had data would be stored and displayed in the colorbar.

```python
# OLD CODE - Bug
im = None
for ptype in precip_types:
    if var_key in ds:
        # ... processing ...
        im = ax.contourf(...)  # This overwrites im each time!
```

## Solution
Modified the code to:
1. Store all precipitation type contourf plots in a dictionary
2. Create separate colorbars for each precipitation type that has data
3. Display all colorbars side-by-side at the bottom of the map

### Changes Made

#### 1. Store All Precipitation Contours (Line ~492)
```python
# Store all precipitation type contourf plots for colorbars
precip_contours = {}

for ptype in precip_types:
    var_key = ptype['key']
    if var_key in ds:
        mask = ds[var_key].isel(time=0) if 'time' in ds[var_key].dims else ds[var_key]
        type_data = data.where(mask > 0.5)
        
        if float(type_data.max()) > 0.005:
            contour = ax.contourf(...)
            precip_contours[var_key] = (contour, ptype['cmap'])

# Set im to first available for compatibility
im = list(precip_contours.values())[0][0] if precip_contours else None
```

#### 2. Create Multiple Colorbars (Line ~788)
```python
elif is_mslp_precip:
    if 'precip_contours' in locals() and precip_contours:
        precip_labels = {
            'crain': 'Rain',
            'csnow': 'Snow',
            'cicep': 'Sleet',
            'cfrzr': 'FrzR'
        }
        
        num_cbars = len(precip_contours)
        cbar_width = 0.85 / num_cbars  # Divide available space
        cbar_height = 0.03
        cbar_bottom = 0.08
        cbar_spacing = 0.02
        
        idx = 0
        for var_key, (contour, cmap_name) in precip_contours.items():
            left_position = 0.10 + idx * (cbar_width + cbar_spacing)
            cbar_ax = fig.add_axes([left_position, cbar_bottom, cbar_width, cbar_height])
            
            cbar = plt.colorbar(contour, cax=cbar_ax, orientation='horizontal')
            tick_positions = [0.1, 0.5, 1, 2.5, 4, 6, 10, 14, 16, 18]
            cbar.set_ticks(tick_positions)
            cbar.set_label(f"{precip_labels.get(var_key, var_key)} (mm/hr)", fontsize=9)
            cbar.ax.tick_params(labelsize=8)
            
            idx += 1
```

## Results
- Each map now displays **all** precipitation type colorbars that have data
- Rain (Greens), Snow (Blues), Sleet (Oranges), and Freezing Rain (RdPu) colorbars appear side-by-side
- Each colorbar is properly labeled with the precipitation type name
- Colorbars are dynamically sized based on how many types are present

## Testing
Successfully tested with multiple forecast hours (6h, 24h, 48h, 54h):
- All maps generated successfully
- File sizes increased slightly due to multiple colorbars (~520-705 KB)
- All precipitation types visible when present in the forecast

## Files Modified
- `/Users/brianaustin/twf_models/backend/app/services/map_generator.py`
  - Lines ~492-518: Modified precipitation plotting logic
  - Lines ~788-823: Modified colorbar creation logic
