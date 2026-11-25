"""Coeur du simulateur: application BACnet/IP + boucle d'animation."""

import asyncio
import logging
import time
from typing import List, Optional, Tuple, Union

from bacpypes3.ipv4.app import BBMDApplication, NormalApplication
from bacpypes3.local.device import DeviceObject
from bacpypes3.object import Object
from bacpypes3.pdu import IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier

from .animations import animate, animation_kind, cast_value
from .config import SimulatorConfig
from .objects import build_object

_log = logging.getLogger("bacnet_simulator")


class BacnetSimulator:
    """Un device BACnet/IP qui heberge des objets animes."""

    def __init__(self, config: SimulatorConfig) -> None:
        self.config = config
        self.app: Optional[Union[NormalApplication, BBMDApplication]] = None
        self.device_object: Optional[DeviceObject] = None
        self.objects: List[Tuple[object, Object]] = []
        self._update_task: Optional[asyncio.Task] = None
        self._start_time: float = 0.0

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
        for obj_cfg in self.config.objects:
            obj = build_object(obj_cfg)
            self.app.add_object(obj)
            self.objects.append((obj_cfg, obj))
        self._start_time = time.monotonic()
        self._update_task = asyncio.create_task(self._update_loop())
        _log.info(
            "device %s (instance %d) en ecoute sur %s avec %d objet(s)",
            dev.name,
            dev.instance,
            dev.bind_address,
            len(self.objects),
        )
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

    async def stop(self) -> None:
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
