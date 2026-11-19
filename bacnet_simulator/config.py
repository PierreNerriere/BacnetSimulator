"""Chargement et validation de la configuration du simulateur (JSON)."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .animations import allowed_animations, animation_kind

SUPPORTED_TYPES = (
    "analogInput",
    "analogOutput",
    "analogValue",
    "binaryInput",
    "binaryOutput",
    "binaryValue",
    "multiStateInput",
    "multiStateOutput",
    "multiStateValue",
)

MAX_INSTANCE = 4194302


@dataclass
class DeviceConfig:
    name: str = "BacnetSimulator"
    instance: int = 1234
    vendor_name: str = "VibeSim"
    vendor_identifier: int = 999
    model_name: str = "BacnetDeviceSimulator"
    firmware_revision: str = "1.0"
    software_version: str = "0.1.0"
    bind_address: str = "0.0.0.0:47808"


@dataclass
class ObjectConfig:
    type: str
    instance: int
    name: str
    description: str = ""
    value: Any = None
    units: Optional[str] = None
    polarity: str = "normal"
    number_of_states: Optional[int] = None
    state_text: Optional[List[str]] = None
    animation: Optional[Dict[str, Any]] = None


@dataclass
class SimulatorConfig:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    objects: List[ObjectConfig] = field(default_factory=list)
    update_interval: float = 1.0


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _parse_device(raw: Dict[str, Any]) -> DeviceConfig:
    _check(isinstance(raw, dict), "'device' doit etre un objet JSON")
    cfg = DeviceConfig(
        name=str(raw.get("name", DeviceConfig.name)),
        instance=int(raw.get("instance", DeviceConfig.instance)),
        vendor_name=str(raw.get("vendor_name", DeviceConfig.vendor_name)),
        vendor_identifier=int(raw.get("vendor_identifier", DeviceConfig.vendor_identifier)),
        model_name=str(raw.get("model_name", DeviceConfig.model_name)),
        firmware_revision=str(raw.get("firmware_revision", DeviceConfig.firmware_revision)),
        software_version=str(raw.get("software_version", DeviceConfig.software_version)),
        bind_address=str(raw.get("bind_address", DeviceConfig.bind_address)),
    )
    _check(0 <= cfg.instance <= MAX_INSTANCE, f"device.instance hors limites: {cfg.instance}")
    _check(cfg.name, "device.name ne peut pas etre vide")
    return cfg


def _parse_object(raw: Dict[str, Any], index: int) -> ObjectConfig:
    _check(isinstance(raw, dict), f"objects[{index}] doit etre un objet JSON")
    obj_type = str(raw.get("type", ""))
    _check(obj_type in SUPPORTED_TYPES, f"objects[{index}].type non supporte: {obj_type!r}")
    instance = int(raw.get("instance", -1))
    _check(0 <= instance <= MAX_INSTANCE, f"objects[{index}].instance hors limites: {instance}")
    name = str(raw.get("name", f"{obj_type}-{instance}"))

    animation = raw.get("animation")
    if animation is not None:
        _check(isinstance(animation, dict), f"objects[{index}].animation doit etre un objet JSON")
        anim_type = str(animation.get("type", "none"))
        _check(
            anim_type in allowed_animations(obj_type),
            f"objects[{index}]: animation {anim_type!r} incompatible avec {obj_type!r} "
            f"(autorisees: {', '.join(allowed_animations(obj_type))})",
        )

    number_of_states = raw.get("number_of_states")
    if number_of_states is not None:
        number_of_states = int(number_of_states)
        _check(
            1 <= number_of_states <= 255,
            f"objects[{index}].number_of_states hors limites: {number_of_states}",
        )
    if animation_kind(obj_type) == "multistate":
        _check(
            number_of_states is not None,
            f"objects[{index}]: 'number_of_states' requis pour {obj_type!r}",
        )

    state_text = raw.get("state_text")
    if state_text is not None:
        _check(
            isinstance(state_text, list) and all(isinstance(s, str) for s in state_text),
            f"objects[{index}].state_text doit etre une liste de chaines",
        )

    return ObjectConfig(
        type=obj_type,
        instance=instance,
        name=name,
        description=str(raw.get("description", "")),
        value=raw.get("value"),
        units=raw.get("units"),
        polarity=str(raw.get("polarity", "normal")),
        number_of_states=number_of_states,
        state_text=state_text,
        animation=animation,
    )


def parse_config(data: Dict[str, Any]) -> SimulatorConfig:
    _check(isinstance(data, dict), "la configuration doit etre un objet JSON")
    device = _parse_device(data.get("device", {}))
    raw_objects = data.get("objects", [])
    _check(isinstance(raw_objects, list), "'objects' doit etre une liste")
    objects = [_parse_object(raw, i) for i, raw in enumerate(raw_objects)]

    seen = set()
    for obj in objects:
        key = (obj.type, obj.instance)
        _check(key not in seen, f"objet duplique: {obj.type}:{obj.instance}")
        seen.add(key)

    update_interval = float(data.get("update_interval", 1.0))
    _check(update_interval > 0, "'update_interval' doit etre > 0")

    return SimulatorConfig(device=device, objects=objects, update_interval=update_interval)


def load_config(path: Union[str, Path]) -> SimulatorConfig:
    path = Path(path)
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return parse_config(data)


def demo_config() -> SimulatorConfig:
    """Configuration de demonstration lancee quand aucun fichier n'est fourni."""
    return parse_config(
        {
            "device": {
                "name": "DemoDevice",
                "instance": 1234,
                "bind_address": "0.0.0.0:47808",
            },
            "update_interval": 1.0,
            "objects": [
                {
                    "type": "analogValue",
                    "instance": 1,
                    "name": "AV-Temperature",
                    "description": "Temperature simulee (sinusoide)",
                    "value": 21.0,
                    "units": "degreesCelsius",
                    "animation": {
                        "type": "sine",
                        "amplitude": 3.0,
                        "period": 60.0,
                        "offset": 21.0,
                    },
                },
                {
                    "type": "analogInput",
                    "instance": 1,
                    "name": "AI-Humidity",
                    "value": 45.0,
                    "units": "percentRelativeHumidity",
                    "animation": {"type": "random", "min": 40.0, "max": 60.0},
                },
                {
                    "type": "binaryValue",
                    "instance": 1,
                    "name": "BV-Pump",
                    "value": "inactive",
                    "animation": {"type": "toggle", "period": 15.0},
                },
                {
                    "type": "multiStateValue",
                    "instance": 1,
                    "name": "MSV-Mode",
                    "value": 1,
                    "number_of_states": 3,
                    "state_text": ["Off", "Auto", "Manual"],
                    "animation": {"type": "cycle", "period": 10.0},
                },
            ],
        }
    )
