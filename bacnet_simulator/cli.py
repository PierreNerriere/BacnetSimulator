"""Point d'entree en ligne de commande du simulateur."""

import argparse
import asyncio
import logging
import sys
from typing import List, Optional

from . import __version__
from .config import SimulatorConfig, demo_config, load_config, parse_bbmd
from .simulator import BacnetSimulator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bacnet-simulator",
        description="Simulateur de device BACnet/IP (Who-Is/IAm, ReadProperty, WriteProperty).",
    )
    parser.add_argument(
        "-c",
        "--config",
        help="fichier de configuration JSON (sans option: configuration de demonstration)",
    )
    parser.add_argument(
        "--address",
        help="adresse UDP d'ecoute, ex. 0.0.0.0:47808 (defaut: 0.0.0.0:47808)",
    )
    parser.add_argument("--instance", type=int, help="numero d'instance du device")
    parser.add_argument("--name", help="nom (objectName) du device")
    parser.add_argument(
        "--bbmd",
        action="store_true",
        help="activer le mode BBMD (Annex J: BDT/FDT, transfert des broadcasts)",
    )
    parser.add_argument(
        "--bbmd-peer",
        action="append",
        default=[],
        metavar="IP:PORT",
        help="peer BBMD a ajouter a la BDT, ex. 10.0.0.2:47808 (option repetable)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="logs de debug bacpypes3"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("bacnet_simulator")

    try:
        config: SimulatorConfig = load_config(args.config) if args.config else demo_config()
    except (OSError, ValueError) as err:
        log.error("configuration invalide: %s", err)
        return 2

    if args.address:
        config.device.bind_address = args.address
    if args.instance is not None:
        config.device.instance = args.instance
    if args.name:
        config.device.name = args.name
    if args.bbmd_peer:
        try:
            config.bbmd = parse_bbmd({"enabled": True, "peers": args.bbmd_peer})
        except ValueError as err:
            log.error("configuration invalide: %s", err)
            return 2
    elif args.bbmd:
        config.bbmd.enabled = True

    simulator = BacnetSimulator(config)
    try:
        asyncio.run(simulator.run_forever())
    except KeyboardInterrupt:
        log.info("arret demande (Ctrl-C)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
