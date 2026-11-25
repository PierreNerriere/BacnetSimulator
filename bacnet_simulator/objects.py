"""Fabrique des objets BACnet locaux a partir de la configuration."""

from typing import Any, Dict, Optional

from bacpypes3.basetypes import (
    BinaryPV,
    EngineeringUnits,
    EventState,
    OptionalUnsigned,
    Polarity,
    PriorityValue,
    StatusFlags,
)
from bacpypes3.local.analog import (
    AnalogInputObject,
    AnalogOutputObject,
    AnalogValueObject,
)
from bacpypes3.local.binary import (
    BinaryInputObject,
    BinaryOutputObject,
    BinaryValueObject,
)
from bacpypes3.local.cov import COVIncrementCriteria, GenericCriteria
from bacpypes3.local.multistate import (
    MultiStateInputObject,
    MultiStateOutputObject,
    MultiStateValueObject,
)
from bacpypes3.object import Object
from bacpypes3.primitivedata import ObjectIdentifier

from .animations import animation_kind
from .config import ObjectConfig
from .enums import BINARY_ACTIVE_TEXT, BINARY_INACTIVE_TEXT, cast_binary, cast_polarity

_OBJECT_CLASSES: Dict[str, type] = {
    "analogInput": AnalogInputObject,
    "analogOutput": AnalogOutputObject,
    "analogValue": AnalogValueObject,
    "binaryInput": BinaryInputObject,
    "binaryOutput": BinaryOutputObject,
    "binaryValue": BinaryValueObject,
    "multiStateInput": MultiStateInputObject,
    "multiStateOutput": MultiStateOutputObject,
    "multiStateValue": MultiStateValueObject,
}

_OUTPUT_TYPES = {"analogOutput", "binaryOutput", "multiStateOutput"}

# criteres de detection COV par type d'objet (comme criteria_type_map de bacpypes3) :
# les objets analogiques utilisent le critere a increment, les autres le critere generique
_COV_CRITERIA: Dict[str, type] = {
    "analogInput": COVIncrementCriteria,
    "analogOutput": COVIncrementCriteria,
    "analogValue": COVIncrementCriteria,
    "binaryInput": GenericCriteria,
    "binaryOutput": GenericCriteria,
    "binaryValue": GenericCriteria,
    "multiStateInput": GenericCriteria,
    "multiStateOutput": GenericCriteria,
    "multiStateValue": GenericCriteria,
}


def _common_kwargs(cfg: ObjectConfig) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "objectIdentifier": ObjectIdentifier((cfg.type, cfg.instance)),
        "objectName": cfg.name,
        "statusFlags": StatusFlags([0, 0, 0, 0]),
        "eventState": EventState("normal"),
        "outOfService": False,
    }
    if cfg.description:
        kwargs["description"] = cfg.description
    return kwargs


def _default_value(cfg: ObjectConfig) -> Any:
    kind = animation_kind(cfg.type)
    if kind == "analog":
        return float(cfg.value) if cfg.value is not None else 0.0
    if kind == "binary":
        return BinaryPV(cast_binary(cfg.value) if cfg.value is not None else "inactive")
    states = cfg.number_of_states or 2
    value = int(cfg.value) if cfg.value is not None else 1
    return max(1, min(states, value))


def _state_text(cfg: ObjectConfig) -> list:
    states = cfg.number_of_states or 2
    if cfg.state_text:
        return list(cfg.state_text)
    return [f"State {i}" for i in range(1, states + 1)]


def build_object(cfg: ObjectConfig) -> Object:
    """Construit un objet BACnet local pour la configuration donnee."""
    cls = _OBJECT_CLASSES[cfg.type]
    kind = animation_kind(cfg.type)
    kwargs = _common_kwargs(cfg)
    value = _default_value(cfg)

    if kind == "analog":
        kwargs["presentValue"] = value
        kwargs["units"] = EngineeringUnits(cfg.units or "noUnits")
        kwargs["covIncrement"] = (
            float(cfg.cov_increment) if cfg.cov_increment is not None else 0.0
        )
    elif kind == "binary":
        kwargs["presentValue"] = value
        kwargs["activeText"] = cfg.active_text or BINARY_ACTIVE_TEXT
        kwargs["inactiveText"] = cfg.inactive_text or BINARY_INACTIVE_TEXT
        if cfg.type in ("binaryInput", "binaryOutput"):
            kwargs["polarity"] = Polarity(cast_polarity(cfg.polarity))
    else:
        kwargs["presentValue"] = value
        kwargs["numberOfStates"] = cfg.number_of_states or 2
        kwargs["stateText"] = _state_text(cfg)

    if cfg.type in _OUTPUT_TYPES:
        kwargs["priorityArray"] = [PriorityValue(null=()) for _ in range(16)]
        kwargs["relinquishDefault"] = value
        kwargs["currentCommandPriority"] = OptionalUnsigned(null=())

    obj = cls(**kwargs)
    obj._cov_criteria = _COV_CRITERIA[cfg.type]
    return obj
