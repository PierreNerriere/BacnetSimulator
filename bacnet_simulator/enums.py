"""Gestion centralisee des enumerations BACnet (alias -> valeur canonique).

Les valeurs d'enumeration BACnet (BinaryPV, Polarity...) n'acceptent que
leurs libelles canoniques anglais ('active'/'inactive', 'normal'/'reverse').
Ce module accepte en plus des alias usuels (francais et anglais, en
majuscules ou non) et normalise tout vers la valeur canonique attendue par
bacpypes3.
"""

from typing import Any, Dict, Mapping

BINARY_PV_ALIASES: Dict[str, str] = {
    "active": "active",
    "actif": "active",
    "on": "active",
    "marche": "active",
    "oui": "active",
    "true": "active",
    "1": "active",
    "inactive": "inactive",
    "inactif": "inactive",
    "off": "inactive",
    "arret": "inactive",
    "non": "inactive",
    "false": "inactive",
    "0": "inactive",
}

POLARITY_ALIASES: Dict[str, str] = {
    "normal": "normal",
    "reverse": "reverse",
    "reversed": "reverse",
    "inverse": "reverse",
    "inversee": "reverse",
}

BINARY_ACTIVE_TEXT = "Actif"
BINARY_INACTIVE_TEXT = "Inactif"


def _canonical(aliases: Mapping[str, str], value: Any, label: str) -> str:
    if isinstance(value, str):
        key = value.strip().lower()
        if key in aliases:
            return aliases[key]
    accepted = ", ".join(sorted(aliases))
    raise ValueError(f"valeur invalide pour {label}: {value!r} (alias acceptes: {accepted})")


def cast_binary(value: Any) -> str:
    """Normalise une valeur binaire en 'active' ou 'inactive'."""
    if isinstance(value, bool):
        return "active" if value else "inactive"
    if isinstance(value, (int, float)):
        return "active" if value else "inactive"
    return _canonical(BINARY_PV_ALIASES, value, "BinaryPV")


def cast_polarity(value: Any) -> str:
    """Normalise une polarite en 'normal' ou 'reverse'."""
    return _canonical(POLARITY_ALIASES, value, "Polarity")
