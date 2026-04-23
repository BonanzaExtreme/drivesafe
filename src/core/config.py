# core/config.py
from __future__ import annotations

import os

import yaml

from .paths import executable_dir, is_frozen, resource_path


def _resolve_resource(rel_or_abs: str) -> str:
    """Resolve config resource paths for source and frozen modes."""
    if not rel_or_abs or os.path.isabs(rel_or_abs):
        return rel_or_abs

    if is_frozen():
        external = os.path.join(executable_dir(), rel_or_abs)
        if os.path.exists(external):
            return external

    return resource_path(rel_or_abs)


def load_config(path: str = "config.yaml") -> dict:
    """Load YAML config file and normalize project-relative resource paths."""
    cfg_path = path
    if not os.path.isabs(path):
        if is_frozen():
            external_cfg = os.path.join(executable_dir(), path)
            if os.path.exists(external_cfg):
                cfg_path = external_cfg
            else:
                cfg_path = resource_path(path)
        else:
            cfg_path = resource_path(path)

    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    model = cfg.get("model", {})
    if "weights" in model:
        model["weights"] = _resolve_resource(model["weights"])

    voice_commands = cfg.get("voice_commands", {})
    if "model_path" in voice_commands:
        voice_commands["model_path"] = _resolve_resource(voice_commands["model_path"])

    alerts = cfg.get("alerts", {})
    if "mode" not in alerts:
        alerts["mode"] = "both"
    if "voice_model" not in alerts:
        alerts["voice_model"] = _resolve_resource("models/voice/en_US-hfc_male-medium (1).onnx")
    if "voice_model" in alerts:
        alerts["voice_model"] = _resolve_resource(alerts["voice_model"])

    return cfg