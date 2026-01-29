#!/bin/bash
# Install Herbie with numpy version constraints
# This script ensures numpy<2.0 compatibility with scipy/matplotlib

echo "========================================"
echo "Installing Herbie with numpy constraints"
echo "========================================"
echo ""

# Check if virtual environment is activated
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Warning: No virtual environment detected"
    echo "   It's recommended to activate your venv first"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "📦 Installing herbie-data with numpy<2.0 constraint..."
pip install herbie-data 'numpy>=1.21.6,<2.0'

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Herbie installed successfully!"
    echo ""
    echo "📊 Verifying installation..."
    python3 -c "
import herbie
import numpy as np
print(f'  ✓ Herbie version: {herbie.__version__}')
print(f'  ✓ NumPy version: {np.__version__}')
assert np.__version__.startswith('1.'), 'NumPy 2.x detected - may cause issues!'
print('')
print('✅ All checks passed!')
"
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "🎉 Herbie is ready for Phase 1 testing!"
        echo ""
        echo "Next steps:"
        echo "  1. Run comparison test: python scripts/tests/test_herbie_comparison.py"
        echo "  2. Review test results"
        echo "  3. Proceed with Phase 2 (HRRR/RAP) if results are positive"
    else
        echo ""
        echo "⚠️  Installation succeeded but verification failed"
        echo "   Check for version conflicts"
    fi
else
    echo ""
    echo "❌ Installation failed"
    echo "   Try manually: pip install herbie-data 'numpy>=1.21.6,<2.0'"
fi
