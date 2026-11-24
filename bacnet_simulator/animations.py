"""Generateurs de valeurs pour animer les objets simules.

Chaque animation recoit le temps ecoule ``t`` (secondes depuis le demarrage)
et retourne la nouvelle valeur de ``presentValue``.
"""

import math
import random
from typing import Any, Dict, Optional

from .enums import cast_binary

ANALOG_ANIMATIONS = ("none", "sine", "ramp", "random", "step")
BINARY_ANIMATIONS = ("none", "toggle")
MULTISTATE_ANIMATIONS = ("none", "cycle")


def animation_kind(object_type: str) -> str:
    if object_type.startswith("analog"):
        return "analog"
    if object_type.startswith("binary"):
        return "binary"
    if object_type.startswith("multiState"):
        return "multistate"
    raise ValueError(f"type d'objet non supporte: {object_type!r}")


def allowed_animations(object_type: str) -> tuple:
    kind = animation_kind(object_type)
    if kind == "analog":
        return ANALOG_ANIMATIONS
    if kind == "binary":
        return BINARY_ANIMATIONS
    return MULTISTATE_ANIMATIONS


def animate(
    animation: Dict[str, Any],
    kind: str,
    base_value: Any,
    t: float,
    number_of_states: int = 1,
) -> Any:
    """Calcule la valeur animee a l'instant ``t``."""
    anim_type = animation.get("type", "none")
    if anim_type == "none":
        return base_value

    if kind == "analog":
        if anim_type == "sine":
            amplitude = float(animation.get("amplitude", 1.0))
            period = float(animation.get("period", 60.0))
            offset = float(animation.get("offset", base_value))
            if period <= 0:
                raise ValueError("animation sine: 'period' doit etre > 0")
            return offset + amplitude * math.sin(2.0 * math.pi * t / period)
        if anim_type == "ramp":
            start = float(animation.get("start", base_value))
            stop = float(animation.get("stop", start))
            duration = float(animation.get("duration", 60.0))
            if duration <= 0:
                raise ValueError("animation ramp: 'duration' doit etre > 0")
            if animation.get("loop", False):
                x = t % duration
            else:
                x = min(t, duration)
            return start + (stop - start) * (x / duration)
        if anim_type == "random":
            low = float(animation.get("min", float(base_value) - 1.0))
            high = float(animation.get("max", float(base_value) + 1.0))
            return random.uniform(low, high)
        if anim_type == "step":
            levels = animation.get("levels") or [base_value]
            duration = float(animation.get("duration", 10.0))
            if duration <= 0:
                raise ValueError("animation step: 'duration' doit etre > 0")
            index = int(t // duration) % len(levels)
            return float(levels[index])
        raise ValueError(f"animation inconnue pour un objet analogique: {anim_type!r}")

    if kind == "binary":
        if anim_type == "toggle":
            period = float(animation.get("period", 10.0))
            if period <= 0:
                raise ValueError("animation toggle: 'period' doit etre > 0")
            return "active" if int(t // period) % 2 == 0 else "inactive"
        raise ValueError(f"animation inconnue pour un objet binaire: {anim_type!r}")

    if kind == "multistate":
        if anim_type == "cycle":
            states = max(1, number_of_states)
            period = float(animation.get("period", 10.0))
            if period <= 0:
                raise ValueError("animation cycle: 'period' doit etre > 0")
            return (int(t // period) % states) + 1
        raise ValueError(f"animation inconnue pour un objet multi-etats: {anim_type!r}")

    raise ValueError(f"genre d'objet inconnu: {kind!r}")


def cast_value(kind: str, value: Any) -> Any:
    """Convertit une valeur JSON/python en valeur presentValue BACnet."""
    if kind == "analog":
        return float(value)
    if kind == "binary":
        return cast_binary(value)
    return int(value)
