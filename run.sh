#!/bin/bash
# ═══════════════════════════════════════════════════════════════
#  LoungeAI #50 — Premium Guest Face-Recognition Entry System
#  Setup & Launch Script
# ═══════════════════════════════════════════════════════════════

set -e

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║       LoungeAI #50 — Biometric Entry System          ║"
echo "║     Airport Lounge · Face Recognition · ArcFace      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

# ── Check Python version ─────────────────────────────────────
PYTHON_MIN="3.9"
python3 -c "
import sys
v = sys.version_info
if v.major < 3 or (v.major == 3 and v.minor < 9):
    print(f'ERROR: Python 3.9+ required (found {v.major}.{v.minor})')
    sys.exit(1)
print(f'✅ Python {v.major}.{v.minor}.{v.micro}')
"

# ── Create virtual environment ────────────────────────────────
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
echo "✅ Virtual environment activated"

# ── Install dependencies ──────────────────────────────────────
echo ""
echo "📥 Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "✅ Dependencies installed"

# ── Create directory structure ────────────────────────────────
echo ""
echo "📁 Creating project structure..."
mkdir -p database logs models

# Create sample database structure for demo members
mkdir -p database/M001 database/M002 database/M003 database/M004
echo "✅ Database directories created"

# ── Check DeepFace availability ───────────────────────────────
echo ""
echo "🔬 Checking AI models..."
python3 -c "
try:
    from deepface import DeepFace
    print('✅ DeepFace: Available')
except ImportError:
    print('⚠️  DeepFace: Not installed - running in SIMULATION mode')

try:
    import faiss
    print('✅ FAISS: Available')
except ImportError:
    print('⚠️  FAISS: Not installed - using linear fallback')

try:
    import cv2
    print(f'✅ OpenCV: {cv2.__version__}')
except ImportError:
    print('❌ OpenCV: MISSING - required')
"

# ── Launch ────────────────────────────────────────────────────
echo ""
echo "🚀 Starting LoungeAI System..."
echo ""
echo "  Dashboard: http://localhost:5000"
echo "  Video Feed: http://localhost:5000/video_feed"
echo "  API State: http://localhost:5000/api/state"
echo ""
echo "  Controls:"
echo "  ├── Click 'Simulate Entry' to demo a recognition event"  
echo "  ├── Click 'Simulate Spoof' to demo anti-spoof detection"
echo "  ├── Click '+Enroll Member' to add a new biometric profile"
echo "  └── Press Ctrl+C to stop"
echo ""

python3 app.py
