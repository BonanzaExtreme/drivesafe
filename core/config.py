# core/config.py
import yaml

def load_config(path="config.yaml"):
    """Load YAML config file. Returns a plain dict."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)