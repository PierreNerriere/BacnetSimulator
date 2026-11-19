"""Petit client BACnet/IP en ligne de commande pour tester le simulateur.

Exemples:
    python -m bacnet_simulator.client --address 127.0.0.1:47808 list
    python -m bacnet_simulator.client --address 127.0.0.1:47808 read analogValue:1 presentValue
    python -m bacnet_simulator.client --address 127.0.0.1:47808 write analogValue:1 presentValue 42.5
    python -m bacnet_simulator.client --address 127.0.0.1:47808 who-is
"""

import argparse
import asyncio
import os
import sys
from typing import Any, List, Optional

from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.ipv4.bvll import (
    LPCI,
    LPDU,
    ReadBroadcastDistributionTable,
    ReadForeignDeviceTable,
    Result,
    pdu_types,
)
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import IPv4Address, PDU
from bacpypes3.primitivedata import ObjectIdentifier


def _client_device() -> DeviceObject:
    instance = 900000 + (os.getpid() % 100000)
    return DeviceObject(
        objectName=f"SimClient-{os.getpid()}",
        objectIdentifier=ObjectIdentifier(("device", instance)),
        vendorName="VibeSim",
        vendorIdentifier=999,
        modelName="BacnetSimulatorClient",
        firmwareRevision="1.0",
        applicationSoftwareVersion="0.1.0",
        maxApduLengthAccepted=1476,
        segmentationSupported="segmentedBoth",
    )


def _cast_write_value(raw: str) -> Any:
    low = raw.strip().lower()
    if low in ("active", "inactive"):
        return low
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


async def _bvll_request(target: IPv4Address, request_lpdu: LPDU, timeout: float) -> LPDU:
    """Envoie une BVLL (Annex J) a un BBMD sur un socket UDP jetable et decode la reponse."""
    loop = asyncio.get_running_loop()
    received: asyncio.Future = loop.create_future()

    class _Proto(asyncio.DatagramProtocol):
        def datagram_received(self, data: bytes, addr) -> None:
            if not received.done():
                received.set_result(data)

    transport, _ = await loop.create_datagram_endpoint(_Proto, local_addr=("0.0.0.0", 0))
    try:
        transport.sendto(request_lpdu.encode().pduData, target.addrTuple)
        data = await asyncio.wait_for(received, timeout)
    finally:
        transport.close()
    resp = PDU(data)
    lpci = LPCI.decode(resp)
    lpdu_class = pdu_types.get(lpci.bvlciFunction)
    if lpdu_class is None:
        raise ValueError(f"fonction BVLL inconnue: {lpci.bvlciFunction:#04x}")
    lpdu = lpdu_class.decode(resp)
    LPCI.update(lpdu, lpci)
    return lpdu


async def _bbmd_command(args: argparse.Namespace, target: IPv4Address) -> int:
    if args.command == "read-bdt":
        ack = await _bvll_request(target, ReadBroadcastDistributionTable(), args.timeout)
        if isinstance(ack, Result):
            print(f"erreur du BBMD: {ack.bvlciResultCode:#06x}")
            return 1
        print(f"{len(ack.bvlciBDT)} entree(s) dans la BDT de {args.address}:")
        for entry in ack.bvlciBDT:
            print(f"  {entry}")
        return 0
    if args.command == "read-fdt":
        ack = await _bvll_request(target, ReadForeignDeviceTable(), args.timeout)
        if isinstance(ack, Result):
            print(f"erreur du BBMD: {ack.bvlciResultCode:#06x}")
            return 1
        print(f"{len(ack.bvlciFDT)} entree(s) dans la FDT de {args.address}:")
        for entry in ack.bvlciFDT:
            print(f"  {entry.fdAddress} (ttl={entry.fdTTL}, restant={entry.fdRemain})")
        return 0
    raise ValueError(f"commande inconnue: {args.command!r}")


async def _run(args: argparse.Namespace) -> int:
    target = IPv4Address(args.address)

    if args.command in ("read-bdt", "read-fdt"):
        return await _bbmd_command(args, target)

    app = NormalApplication(
        _client_device(), IPv4Address(args.local_address or "0.0.0.0:0")
    )
    try:
        if args.command == "who-is":
            address = None if args.broadcast else target
            i_ams = await app.who_is(address=address, timeout=args.timeout)
            if not i_ams:
                print("aucune reponse I-Am")
                return 1
            for i_am in i_ams:
                print(
                    f"device {i_am.iAmDeviceIdentifier[1]} at {i_am.pduSource} "
                    f"maxAPDU={i_am.maxAPDULengthAccepted} segmentation={i_am.segmentationSupported}"
                )
            return 0

        if args.command == "read":
            value = await app.read_property(
                target, args.objid, args.prop, array_index=args.index
            )
            print(value)
            return 0

        if args.command == "write":
            await app.write_property(
                target,
                args.objid,
                args.prop,
                _cast_write_value(args.value),
                array_index=args.index,
                priority=args.priority,
            )
            print("OK")
            return 0

        if args.command == "list":
            obj_list = await app.read_property(target, args.device, "objectList")
            print(f"{len(obj_list)} objet(s) sur device {args.device}:")
            for objid in obj_list:
                name = await app.read_property(target, objid, "objectName")
                print(f"  {objid[0]}:{objid[1]}  {name}")
            return 0

        raise ValueError(f"commande inconnue: {args.command!r}")
    finally:
        app.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bacnet-simulator-client",
        description="Client BACnet/IP minimal pour interroger un device.",
    )
    parser.add_argument(
        "--address",
        required=True,
        help="adresse du device cible, ex. 127.0.0.1:47808",
    )
    parser.add_argument(
        "--local-address",
        default=None,
        help="adresse locale du client, ex. 0.0.0.0:47809 (defaut: port ephemere)",
    )
    parser.add_argument("--timeout", type=float, default=3.0, help="timeout who-is (s)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_whois = sub.add_parser("who-is", help="envoyer Who-Is et afficher les I-Am")
    p_whois.add_argument(
        "--broadcast", action="store_true", help="Who-Is en broadcast (defaut: unicast)"
    )

    p_read = sub.add_parser("read", help="lire une propriete")
    p_read.add_argument("objid", help="ex. analogValue:1")
    p_read.add_argument("prop", help="ex. presentValue")
    p_read.add_argument("--index", type=int, default=None, help="index de tableau")

    p_write = sub.add_parser("write", help="ecrire une propriete")
    p_write.add_argument("objid", help="ex. analogValue:1")
    p_write.add_argument("prop", help="ex. presentValue")
    p_write.add_argument("value", help="ex. 42.5 ou active")
    p_write.add_argument("--index", type=int, default=None, help="index de tableau")
    p_write.add_argument("--priority", type=int, default=None, help="priorite 1-16")

    p_list = sub.add_parser("list", help="lister les objets du device")
    p_list.add_argument(
        "--device", default="device:1234", help="objet device cible (defaut: device:1234)"
    )

    sub.add_parser(
        "read-bdt", help="lire la BDT d'un BBMD (Read-Broadcast-Distribution-Table)"
    )
    sub.add_parser(
        "read-fdt", help="lire la FDT d'un BBMD (Read-Foreign-Device-Table)"
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
