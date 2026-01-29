#!/usr/bin/env python3
"""Test GFS f000 fetch with Herbie"""
import os
import sys

# Set storage path before imports
os.environ['STORAGE_PATH'] = '/Users/brianaustin/twf_models/images'

# Add backend to path
sys.path.insert(0, '/Users/brianaustin/twf_models/backend')

from app.services.model_factory import ModelFactory
from app.models.variable_requirements import VariableRegistry

print('Testing GFS f000 fetch with Herbie...')
print('='*60)

try:
    factory = ModelFactory()
    fetcher = factory.create_fetcher('GFS')
    print(f'✓ Fetcher type: {type(fetcher).__name__}')
    
    # Get latest run time
    run_time = fetcher.get_latest_run_time()
    print(f'✓ Latest run: {run_time}')
    
    # Test fetch for f000 with minimal fields
    var_req = VariableRegistry.get('temp')
    fields = var_req.raw_fields
    print(f'✓ Fetching fields for temperature: {fields}')
    
    print('\nAttempting to fetch f000 data...')
    ds = fetcher.fetch_raw_data(run_time, 0, fields, subset_region=True)
    
    print('\n' + '='*60)
    print('✓ SUCCESS! Retrieved f000 data')
    print(f'  Variables: {list(ds.data_vars)}')
    print(f'  Dimensions: {dict(ds.dims)}')
    print(f'  Coordinate names: {list(ds.coords)}')
    print('='*60)
    
except Exception as e:
    print('\n' + '='*60)
    print(f'✗ FAILED: {e}')
    print('='*60)
    import traceback
    traceback.print_exc()
    sys.exit(1)
