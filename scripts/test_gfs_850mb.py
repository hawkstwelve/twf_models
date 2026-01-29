#!/usr/bin/env python3
"""Test GFS 850mb variable fetching with underscored names"""
import os
import sys

# Set storage path before imports
os.environ['STORAGE_PATH'] = '/Users/brianaustin/twf_models/images'

# Add backend to path
sys.path.insert(0, '/Users/brianaustin/twf_models/backend')

from app.services.model_factory import ModelFactory
from app.models.variable_requirements import VariableRegistry

print('Testing GFS 850mb variables (underscored names)...')
print('='*80)

try:
    factory = ModelFactory()
    fetcher = factory.create_fetcher('GFS')
    print(f'✓ Fetcher type: {type(fetcher).__name__}')
    
    # Get latest run time
    run_time = fetcher.get_latest_run_time()
    print(f'✓ Latest run: {run_time}')
    
    # Test fetch for temp_850_wind_mslp requirements
    var_req = VariableRegistry.get('temp_850_wind_mslp')
    fields = var_req.raw_fields
    print(f'✓ Required fields: {fields}')
    
    print('\nFetching f006 data (should have 850mb fields)...')
    ds = fetcher.fetch_raw_data(run_time, 6, fields, subset_region=True)
    
    print(f'\n✓ SUCCESS!')
    print(f'  Variables in dataset: {list(ds.data_vars)}')
    print(f'  Dimensions: {dict(ds.sizes)}')
    
    # Check for underscored names
    expected = ['tmp_850', 'ugrd_850', 'vgrd_850', 'prmsl']
    found = []
    missing = []
    
    for var in expected:
        if var in ds.data_vars:
            found.append(var)
            shape = ds[var].shape
            ndim = ds[var].ndim
            print(f'  ✓ {var} present - shape: {shape}, ndim: {ndim}')
            if ndim != 2:
                print(f'    ⚠ WARNING: Expected 2D, got {ndim}D')
        else:
            missing.append(var)
            print(f'  ✗ {var} MISSING')
    
    if missing:
        print(f'\n❌ FAILED: Missing variables: {missing}')
        print(f'   Available: {list(ds.data_vars)}')
        sys.exit(1)
    
    # Check all variables are 2D
    non_2d = [var for var in expected if var in ds.data_vars and ds[var].ndim != 2]
    if non_2d:
        print(f'\n❌ FAILED: Non-2D variables: {non_2d}')
        for var in non_2d:
            print(f'   {var}: {ds[var].shape} (dims: {ds[var].dims})')
        sys.exit(1)
    else:
        print(f'\n✅ ALL VARIABLES ARE 2D AND PRESENT')
        
except Exception as e:
    print(f'\n✗ FAILED: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
