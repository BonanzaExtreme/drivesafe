#!/usr/bin/env bash
# setup_jetson.sh – Complete Jetson Orin Nano setup for DriveSafe
# Run this once after first boot. Takes ~15 min (torchvision build + TRT export).
# Usage:  bash setup_jetson.sh

set -e
cd "$(dirname "$0")"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $1"; }
error() { echo -e "${RED}[error]${NC} $1"; exit 1; }

# ── 1. Verify CUDA torch ─────────────────────────────────────────────────────
info "Checking CUDA torch..."
python - <<'EOF'
import torch, sys
if not torch.cuda.is_available():
    print("CUDA NOT available – run install steps first")
    sys.exit(1)
print(f"  torch {torch.__version__} | GPU: {torch.cuda.get_device_name(0)}")
EOF

# ── 2. torchvision – build from source if not present ───────────────────────
info "Checking torchvision..."
if python -c "import torchvision; print(f'  torchvision {torchvision.__version__}')" 2>/dev/null; then
    info "torchvision already installed."
else
    warn "torchvision not found – building from source (10-20 min)..."
    TV_DIR=/tmp/vision
    if [ ! -d "$TV_DIR" ]; then
        git clone --branch v0.20.0 --depth 1 https://github.com/pytorch/vision.git "$TV_DIR"
    fi
    cd "$TV_DIR"
    MAX_JOBS=4 FORCE_CUDA=1 python setup.py bdist_wheel
    pip install dist/torchvision-*.whl
    cd -
    info "torchvision installed."
fi

# ── 3. Export best.pt → best.engine (TensorRT FP16) ─────────────────────────
if [ -f best.engine ]; then
    info "best.engine already exists – skipping export."
else
    info "Exporting best.pt → best.engine (TensorRT FP16) ..."
    python - <<'EOF'
from ultralytics import YOLO
model = YOLO("best.pt")
model.export(format="engine", device=0, half=True, imgsz=640)
print("  Export complete: best.engine")
EOF
    info "TensorRT engine ready."
fi

# ── 4. Update config to use TRT engine ──────────────────────────────────────
info "Updating config.yaml to use best.engine ..."
python - <<'EOF'
import yaml, pathlib
path = pathlib.Path("config.yaml")
cfg = yaml.safe_load(path.read_text())
cfg["model"]["weights"] = "best.engine"
cfg["model"]["device"]  = "0"
cfg["model"]["half"]    = True
path.write_text(yaml.dump(cfg, default_flow_style=False, sort_keys=False))
print("  config.yaml updated.")
EOF

echo ""
info "Setup complete! Run DriveSafe with:  bash run.sh"
