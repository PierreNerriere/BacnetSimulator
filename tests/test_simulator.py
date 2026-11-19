"""Tests d'integration: simulateur + client BACnet/IP sur loopback (127.0.0.1)."""

import asyncio
import socket
import unittest

from bacpypes3.ipv4.app import BBMDApplication, NormalApplication
from bacpypes3.ipv4.bvll import (
    LPCI,
    ForwardedNPDU,
    ReadBroadcastDistributionTable,
    ReadForeignDeviceTable,
    RegisterForeignDevice,
    Result,
    pdu_types,
)
from bacpypes3.pdu import IPv4Address, LocalBroadcast, PDU

from bacnet_simulator.client import _bvll_request, _client_device
from bacnet_simulator.config import parse_config
from bacnet_simulator.simulator import BacnetSimulator


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _decode_bvll(data: bytes):
    resp = PDU(data)
    lpci = LPCI.decode(resp)
    lpdu_class = pdu_types[lpci.bvlciFunction]
    lpdu = lpdu_class.decode(resp)
    LPCI.update(lpdu, lpci)
    return lpdu


async def _make_udp_endpoint(port: int):
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    class Proto(asyncio.DatagramProtocol):
        def datagram_received(self, data, addr) -> None:
            queue.put_nowait(data)

    transport, _ = await loop.create_datagram_endpoint(
        Proto, local_addr=("127.0.0.1", port)
    )
    return transport, queue


def _test_config(server_port: int) -> dict:
    return {
        "device": {
            "name": "TestDevice",
            "instance": 5678,
            "bind_address": f"127.0.0.1:{server_port}",
        },
        "update_interval": 0.1,
        "objects": [
            {
                "type": "analogValue",
                "instance": 1,
                "name": "AV-Static",
                "value": 10.0,
                "units": "degreesCelsius",
            },
            {
                "type": "analogValue",
                "instance": 2,
                "name": "AV-Sine",
                "value": 20.0,
                "units": "degreesCelsius",
                "animation": {"type": "sine", "amplitude": 5.0, "period": 1.0, "offset": 20.0},
            },
            {
                "type": "binaryValue",
                "instance": 1,
                "name": "BV-OnOff",
                "value": "inactive",
            },
            {
                "type": "multiStateValue",
                "instance": 1,
                "name": "MSV-Mode",
                "value": 2,
                "number_of_states": 3,
                "state_text": ["Off", "Auto", "Manual"],
            },
        ],
    }


class SimulatorIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server_port = _free_port()
        self.client_port = _free_port()
        self.sim = BacnetSimulator(parse_config(_test_config(self.server_port)))
        await self.sim.start()
        self.client = NormalApplication(
            _client_device(), IPv4Address(f"127.0.0.1:{self.client_port}")
        )
        self.target = IPv4Address(f"127.0.0.1:{self.server_port}")
        await asyncio.sleep(0.1)

    async def asyncTearDown(self) -> None:
        self.client.close()
        await self.sim.stop()

    async def test_read_present_value(self) -> None:
        value = await self.client.read_property(
            self.target, "analogValue:1", "presentValue"
        )
        self.assertAlmostEqual(float(value), 10.0)

    async def test_read_object_name_and_description(self) -> None:
        name = await self.client.read_property(self.target, "analogValue:1", "objectName")
        self.assertEqual(str(name), "AV-Static")

    async def test_write_then_read_present_value(self) -> None:
        await self.client.write_property(
            self.target, "analogValue:1", "presentValue", 42.5
        )
        value = await self.client.read_property(
            self.target, "analogValue:1", "presentValue"
        )
        self.assertAlmostEqual(float(value), 42.5)

    async def test_write_binary_value(self) -> None:
        await self.client.write_property(self.target, "binaryValue:1", "presentValue", "active")
        value = await self.client.read_property(self.target, "binaryValue:1", "presentValue")
        self.assertEqual(str(value), "active")

    async def test_read_multistate(self) -> None:
        value = await self.client.read_property(self.target, "multiStateValue:1", "presentValue")
        self.assertEqual(int(value), 2)
        text = await self.client.read_property(self.target, "multiStateValue:1", "stateText", 3)
        self.assertEqual(str(text), "Manual")

    async def test_object_list(self) -> None:
        obj_list = await self.client.read_property(self.target, "device:5678", "objectList")
        ids = {(str(o[0]), int(o[1])) for o in obj_list}
        self.assertIn(("device", 5678), ids)
        self.assertIn(("analog-value", 1), ids)
        self.assertIn(("analog-value", 2), ids)
        self.assertIn(("binary-value", 1), ids)
        self.assertIn(("multi-state-value", 1), ids)

    async def test_who_is_unicast(self) -> None:
        i_ams = await self.client.who_is(address=self.target, timeout=2)
        instances = [int(i_am.iAmDeviceIdentifier[1]) for i_am in i_ams]
        self.assertIn(5678, instances)

    async def test_animation_changes_value(self) -> None:
        await asyncio.sleep(0.45)
        value = await self.client.read_property(
            self.target, "analogValue:2", "presentValue"
        )
        self.assertGreater(abs(float(value) - 20.0), 0.01)

    async def test_normal_mode_is_not_bbmd(self) -> None:
        self.assertIsInstance(self.sim.app, NormalApplication)
        self.assertFalse(hasattr(self.sim.app, "bbmd"))


class ConfigValidationTest(unittest.TestCase):
    def test_unknown_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"objects": [{"type": "calendar", "instance": 1, "name": "x"}]})

    def test_duplicate_object_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {"type": "analogValue", "instance": 1, "name": "a"},
                        {"type": "analogValue", "instance": 1, "name": "b"},
                    ]
                }
            )

    def test_multistate_requires_number_of_states(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"objects": [{"type": "multiStateValue", "instance": 1, "name": "m"}]})

    def test_bad_animation_for_type_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {
                            "type": "binaryValue",
                            "instance": 1,
                            "name": "b",
                            "animation": {"type": "sine"},
                        }
                    ]
                }
            )

    def test_instance_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {"objects": [{"type": "analogValue", "instance": 4194303, "name": "a"}]}
            )

    def test_demo_config_is_valid(self) -> None:
        from bacnet_simulator.config import demo_config

        cfg = demo_config()
        self.assertEqual(len(cfg.objects), 4)

    def test_bbmd_disabled_by_default(self) -> None:
        cfg = parse_config({"objects": []})
        self.assertFalse(cfg.bbmd.enabled)
        self.assertEqual(cfg.bbmd.peers, [])

    def test_bbmd_peers_parsed(self) -> None:
        cfg = parse_config(
            {"bbmd": {"enabled": True, "peers": ["10.0.0.2:47808", "10.0.0.3:47808"]}}
        )
        self.assertTrue(cfg.bbmd.enabled)
        self.assertEqual(cfg.bbmd.peers, ["10.0.0.2:47808", "10.0.0.3:47808"])

    def test_bbmd_invalid_peer_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"bbmd": {"enabled": True, "peers": ["pas-une-adresse"]}})

    def test_bbmd_peers_not_a_list_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"bbmd": {"peers": "10.0.0.2:47808"}})

    def test_bbmd_section_not_an_object_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"bbmd": True})


class BBMDIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Simulateur en mode BBMD: BDT, transfert des broadcasts, FDT."""

    async def asyncSetUp(self) -> None:
        self.server_port = _free_port()
        self.peer_port = _free_port()
        self.client_port = _free_port()
        raw = _test_config(self.server_port)
        raw["device"]["bind_address"] = f"127.0.0.1/8:{self.server_port}"
        raw["bbmd"] = {"enabled": True, "peers": [f"127.0.0.1:{self.peer_port}"]}
        self.sim = BacnetSimulator(parse_config(raw))
        await self.sim.start()
        self.client = NormalApplication(
            _client_device(), IPv4Address(f"127.0.0.1:{self.client_port}")
        )
        self.target = IPv4Address(f"127.0.0.1:{self.server_port}")
        self.peer_transport, self.peer_queue = await _make_udp_endpoint(self.peer_port)
        await asyncio.sleep(0.1)

    async def asyncTearDown(self) -> None:
        self.peer_transport.close()
        self.client.close()
        await self.sim.stop()

    async def _inject_broadcast(self, payload: bytes = b"\x10\x08") -> None:
        pdu = PDU(
            payload,
            source=IPv4Address(f"127.0.0.1:{self.client_port}"),
            destination=LocalBroadcast(),
        )
        await self.sim.app.bbmd.indication(pdu)

    async def test_bbmd_application_and_bdt(self) -> None:
        self.assertIsInstance(self.sim.app, BBMDApplication)
        bdt = self.sim.app.bbmd.bbmdBDT
        self.assertIn(IPv4Address(f"127.0.0.1:{self.peer_port}"), bdt)

    async def test_bbmd_still_answers_unicast_who_is(self) -> None:
        i_ams = await self.client.who_is(address=self.target, timeout=2)
        instances = [int(i_am.iAmDeviceIdentifier[1]) for i_am in i_ams]
        self.assertIn(5678, instances)

    async def test_read_bdt_over_bvll(self) -> None:
        ack = await _bvll_request(self.target, ReadBroadcastDistributionTable(), 2.0)
        self.assertNotIsInstance(ack, Result)
        self.assertIn(IPv4Address(f"127.0.0.1:{self.peer_port}"), ack.bvlciBDT)

    async def test_broadcast_forwarded_to_bdt_peer(self) -> None:
        await self._inject_broadcast(b"\x10\x08")
        data = await asyncio.wait_for(self.peer_queue.get(), 2.0)
        lpdu = _decode_bvll(data)
        self.assertIsInstance(lpdu, ForwardedNPDU)
        self.assertEqual(lpdu.bvlciAddress, self.sim.app.bbmd.bbmdAddress)
        self.assertEqual(bytes(lpdu.pduData), b"\x10\x08")

    async def test_foreign_device_registration_and_forwarding(self) -> None:
        fd_port = _free_port()
        fd_transport, fd_queue = await _make_udp_endpoint(fd_port)
        try:
            req = RegisterForeignDevice(120)
            fd_transport.sendto(req.encode().pduData, self.target.addrTuple)
            data = await asyncio.wait_for(fd_queue.get(), 2.0)
            result = _decode_bvll(data)
            self.assertIsInstance(result, Result)
            self.assertEqual(result.bvlciResultCode, 0)

            fdt = await _bvll_request(self.target, ReadForeignDeviceTable(), 2.0)
            self.assertNotIsInstance(fdt, Result)
            self.assertEqual(len(fdt.bvlciFDT), 1)
            self.assertEqual(int(fdt.bvlciFDT[0].fdAddress.addrPort), fd_port)

            await self._inject_broadcast(b"\x10\x08")
            data = await asyncio.wait_for(fd_queue.get(), 2.0)
            lpdu = _decode_bvll(data)
            self.assertIsInstance(lpdu, ForwardedNPDU)
            self.assertEqual(bytes(lpdu.pduData), b"\x10\x08")
        finally:
            fd_transport.close()


if __name__ == "__main__":
    unittest.main()
