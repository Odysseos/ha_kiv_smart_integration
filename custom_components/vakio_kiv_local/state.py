# SPDX-License-Identifier: GPL-3.0-only
"""Device state, independent of MQTT transport and Home Assistant."""
from dataclasses import asdict, dataclass, replace
import json
import math


@dataclass(frozen=True)
class ValveState:
    mode: str = "manual"
    power: str = "on"
    gate: int = 1

    @classmethod
    def load(cls, value):
        if not isinstance(value, dict):
            return None
        if (value.get("mode") not in ("manual", "super_auto")
                or value.get("power") not in ("on", "off")
                or type(value.get("gate")) is not int or value["gate"] not in range(1, 5)):
            return None
        return cls(value["mode"], value["power"], value["gate"])

    @classmethod
    def seasonal(cls, month):
        gate = 4 if month in (5, 6, 7, 8, 9) else 3 if month in (4, 10) else 2 if month in (3, 11) else 1
        return cls(gate=gate)

    def merge(self, caps):
        if not isinstance(caps, dict):
            return self
        changes = {}
        if caps.get("mode") in ("manual", "super_auto"):
            changes["mode"] = caps["mode"]
        if caps.get("on_off") in ("on", "off"):
            changes["power"] = caps["on_off"]
        if type(caps.get("gate")) is int and caps["gate"] in range(1, 5):
            changes["gate"] = caps["gate"]
        return replace(self, **changes)

    def dump(self):
        return asdict(self)

    @property
    def position(self):
        return 0 if self.power == "off" else self.gate * 25

    @property
    def option(self):
        if self.mode == "super_auto":
            return "Авто"
        return "Нет" if self.power == "off" else {1: "Малое", 2: "Среднее", 3: "Большое", 4: "Полное"}[self.gate]


def capabilities(payload):
    try:
        msg = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    caps = msg.get("capabilities") if isinstance(msg, dict) else None
    return caps if isinstance(caps, dict) else {}


def measurement(payload, humidity=False):
    try:
        value = float(payload)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(value) or (humidity and not 0 <= value <= 100):
        return None
    return value
