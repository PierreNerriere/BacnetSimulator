"""Coeur du simulateur: application BACnet/IP + boucle d'animation."""

import asyncio
import concurrent.futures
import logging
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from bacpypes3.ipv4.app import BBMDApplication, NormalApplication
from bacpypes3.local.device import DeviceObject
from bacpypes3.object import Object
from bacpypes3.pdu import IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier

from .animations import (
    allowed_animations,
    animate,
    animation_kind,
    cast_value,
    validate_animation,
)
from .config import SimulatorConfig
from .network import apply_broadcast_address
from .objects import build_object, is_writable
from .webui import WebUI

_log = logging.getLogger("bacnet_simulator")


class BacnetSimulator:
    """Un device BACnet/IP qui heberge des objets animes."""

    def __init__(
        self, config: SimulatorConfig, web_address: Optional[str] = None
    ) -> None:
        self.config = config
        self.app: Optional[Union[NormalApplication, BBMDApplication]] = None
        self.device_object: Optional[DeviceObject] = None
        self.objects: List[Tuple[object, Object]] = []
        self._update_task: Optional[asyncio.Task] = None
        self._start_time: float = 0.0
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._web_address = web_address
        self._web: Optional[WebUI] = None

    async def start(self) -> None:
        dev = self.config.device
        self.device_object = DeviceObject(
            objectName=dev.name,
            objectIdentifier=ObjectIdentifier(("device", dev.instance)),
            vendorName=dev.vendor_name,
            vendorIdentifier=dev.vendor_identifier,
            modelName=dev.model_name,
            firmwareRevision=dev.firmware_revision,
            applicationSoftwareVersion=dev.software_version,
            maxApduLengthAccepted=1476,
            segmentationSupported="segmentedBoth",
        )
        bind_address = IPv4Address(dev.bind_address)
        if self.config.bbmd.enabled:
            self.app = BBMDApplication(self.device_object, bind_address)
            for peer in self.config.bbmd.peers:
                self.app.add_peer(IPv4Address(peer))
        else:
            self.app = NormalApplication(self.device_object, bind_address)
        broadcast = apply_broadcast_address(self.app, dev.bind_address, dev.broadcast_address)
        for obj_cfg in self.config.objects:
            obj = build_object(obj_cfg)
            self.app.add_object(obj)
            self.objects.append((obj_cfg, obj))
        self._start_time = time.monotonic()
        self._loop = asyncio.get_running_loop()
        self._update_task = asyncio.create_task(self._update_loop())
        if self._web_address:
            host, _, port = self._web_address.rpartition(":")
            self._web = WebUI(self, host or "127.0.0.1", int(port))
            self._web.start()
        _log.info(
            "device %s (instance %d) en ecoute sur %s avec %d objet(s)",
            dev.name,
            dev.instance,
            dev.bind_address,
            len(self.objects),
        )
        if broadcast is not None:
            _log.info("adresse de broadcast: %s:%d", broadcast[0], broadcast[1])
        if self.config.bbmd.enabled and isinstance(self.app, BBMDApplication):
            _log.info(
                "mode BBMD actif (Annex J), BDT: %s",
                ", ".join(str(bdte) for bdte in self.app.bbmd.bbmdBDT) or "(vide)",
            )
        for obj_cfg, _ in self.objects:
            _log.info("  - %s:%d (%s)", obj_cfg.type, obj_cfg.instance, obj_cfg.name)

    async def _update_loop(self) -> None:
        interval = self.config.update_interval
        while True:
            self.update_once()
            await asyncio.sleep(interval)

    def update_once(self) -> None:
        """Applique les animations a l'instant courant (utile pour les tests)."""
        t = time.monotonic() - self._start_time
        for obj_cfg, obj in self.objects:
            if obj_cfg.animation is None:
                continue
            kind = animation_kind(obj_cfg.type)
            value = animate(
                obj_cfg.animation,
                kind,
                obj_cfg.value,
                t,
                obj_cfg.number_of_states or 1,
            )
            obj.presentValue = cast_value(kind, value)

    @property
    def web_port(self) -> Optional[int]:
        """Port HTTP reel de l'interface web (None si desactivee)."""
        return self._web.address[1] if self._web is not None else None

    def _describe(self, obj_cfg: Any, obj: Object) -> Dict[str, Any]:
        kind = animation_kind(obj_cfg.type)
        present = obj.presentValue
        if kind == "analog":
            value: Any = float(present)
        elif kind == "binary":
            value = str(present)
        else:
            value = int(present)
        return {
            "id": f"{obj_cfg.type}:{obj_cfg.instance}",
            "type": obj_cfg.type,
            "instance": obj_cfg.instance,
            "name": obj_cfg.name,
            "description": obj_cfg.description,
            "kind": kind,
            "value": value,
            "units": obj_cfg.units,
            "writable": is_writable(obj_cfg.type),
            "animation": (obj_cfg.animation or {}).get("type", "none"),
            "animation_params": obj_cfg.animation,
            "number_of_states": obj_cfg.number_of_states,
            "state_text": obj_cfg.state_text,
        }

    def describe_objects(self) -> List[Dict[str, Any]]:
        """Description JSON de tous les objets et de leur valeur courante."""
        return [self._describe(obj_cfg, obj) for obj_cfg, obj in self.objects]

    def describe(self) -> Dict[str, Any]:
        dev = self.config.device
        return {
            "device": {"name": dev.name, "instance": dev.instance},
            "animations": {
                "analog": list(allowed_animations("analogValue")),
                "binary": list(allowed_animations("binaryValue")),
                "multistate": list(allowed_animations("multiStateValue")),
            },
            "objects": self.describe_objects(),
        }

    def _find_object(self, obj_id: str) -> Tuple[Any, Object, str]:
        obj_type, _, raw_instance = obj_id.partition(":")
        try:
            instance = int(raw_instance)
        except ValueError:
            raise ValueError(
                f"identifiant d'objet invalide: {obj_id!r} (attendu: 'type:instance')"
            )
        for obj_cfg, obj in self.objects:
            if obj_cfg.type == obj_type and obj_cfg.instance == instance:
                return obj_cfg, obj, obj_type
        raise KeyError(obj_id)

    def set_value(self, obj_id: str, value: Any) -> Dict[str, Any]:
        """Modifie la valeur d'un objet (appelable depuis n'importe quel thread)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            future: concurrent.futures.Future = concurrent.futures.Future()

            def _apply() -> None:
                try:
                    future.set_result(self._set_value_sync(obj_id, value))
                except Exception as exc:
                    future.set_exception(exc)

            self._loop.call_soon_threadsafe(_apply)
            return future.result(timeout=5.0)
        return self._set_value_sync(obj_id, value)

    def set_animation(self, obj_id: str, animation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Choisit l'animation d'un objet (appelable depuis n'importe quel thread)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            future: concurrent.futures.Future = concurrent.futures.Future()

            def _apply() -> None:
                try:
                    future.set_result(self._set_animation_sync(obj_id, animation))
                except Exception as exc:
                    future.set_exception(exc)

            self._loop.call_soon_threadsafe(_apply)
            return future.result(timeout=5.0)
        return self._set_animation_sync(obj_id, animation)

    def _set_animation_sync(
        self, obj_id: str, animation: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        obj_cfg, obj, obj_type = self._find_object(obj_id)
        if animation is None:
            animation = {"type": "none"}
        validate_animation(obj_type, animation)
        if str(animation.get("type", "none")) == "none":
            obj_cfg.animation = None
        else:
            obj_cfg.animation = dict(animation)
        return self._describe(obj_cfg, obj)

    def _set_value_sync(self, obj_id: str, value: Any) -> Dict[str, Any]:
        if value is None:
            raise ValueError("'value' est requis")
        obj_cfg, obj, obj_type = self._find_object(obj_id)
        if not is_writable(obj_type):
            raise ValueError(
                f"l'objet {obj_id} n'est pas ecrivable "
                "(seuls les *Value et *Output le sont)"
            )
        kind = animation_kind(obj_type)
        if kind == "multistate":
            states = obj_cfg.number_of_states or 1
            obj.presentValue = max(1, min(states, int(value)))
        else:
            obj.presentValue = cast_value(kind, value)
        obj_cfg.animation = None
        return self._describe(obj_cfg, obj)

    async def stop(self) -> None:
        if self._web is not None:
            await asyncio.to_thread(self._web.stop)
            self._web = None
        if self._update_task is not None:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass
            self._update_task = None
        if self.app is not None:
            self.app.close()
            self.app = None

    async def run_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()
