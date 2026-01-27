#!/bin/bash
# Helper script to check Python environment on server

echo "======================================"
echo "Python Environment Check"
echo "======================================"
echo ""

echo "1. Checking for virtual environments..."
if [ -d "venv" ]; then
    echo "   ✓ Found: venv/"
    echo "   Python: $(venv/bin/python3 --version 2>&1)"
fi

if [ -d ".venv" ]; then
    echo "   ✓ Found: .venv/"
    echo "   Python: $(.venv/bin/python3 --version 2>&1)"
fi

if [ -d "env" ]; then
    echo "   ✓ Found: env/"
    echo "   Python: $(env/bin/python3 --version 2>&1)"
fi

echo ""
echo "2. System Python..."
echo "   $(which python3)"
echo "   $(python3 --version 2>&1)"

echo ""
echo "3. Checking matplotlib..."
if [ -d "venv" ]; then
    echo "   In venv:"
    venv/bin/python3 -c "import matplotlib; print('   ✓ matplotlib version:', matplotlib.__version__)" 2>&1
fi

echo "   In system Python:"
python3 -c "import matplotlib; print('   ✓ matplotlib version:', matplotlib.__version__)" 2>&1 || echo "   ✗ matplotlib not found in system Python"

echo ""
echo "======================================"
echo "RECOMMENDATION:"
echo "======================================"
if [ -d "venv" ]; then
    echo "Run test scripts with:"
    echo "  source venv/bin/activate"
    echo "  python3 test_precip_map.py"
    echo ""
    echo "Or directly:"
    echo "  venv/bin/python3 test_precip_map.py"
else
    echo "No virtual environment found."
    echo "Create one with:"
    echo "  python3 -m venv venv"
    echo "  source venv/bin/activate"
    echo "  pip install -r backend/requirements.txt"
fi
