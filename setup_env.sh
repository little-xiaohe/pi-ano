#!/usr/bin/env bash
set -e  # Exit immediately if any command fails

# === 1. Configuration ===
VENV_DIR=".venv"
REQ_FILE="requirements.txt"

# === 2. Remove existing venv (optional but keeps environment clean) ===
if [[ -d "$VENV_DIR" ]]; then
    echo "♻️ Removing existing virtual environment..."
    rm -rf "$VENV_DIR"
fi

# === 3. Detect python executable (python3 on macOS, python on some systems) ===
PY=$(command -v python3 || command -v python)

echo "🔧 Using Python interpreter: $PY"
echo "🔧 Creating virtual environment at: $VENV_DIR"

# === 4. Create virtual environment ===
$PY -m venv "$VENV_DIR"

# === 5. Activate the venv (for installation inside this script) ===
source "$VENV_DIR/bin/activate"

echo "🐍 Python version inside venv:"
python --version

# === 6. Install dependencies from requirements.txt (if exists) ===
if [[ -f "$REQ_FILE" ]]; then
    echo "📦 Installing packages from $REQ_FILE ..."
    pip install --upgrade pip
    pip install -r "$REQ_FILE"
else
    echo "⚠️  $REQ_FILE not found. Skipping installation."
fi

echo "🎉 Environment setup complete!"
echo "👉 To activate the environment manually, run:"
echo "    source $VENV_DIR/bin/activate"
