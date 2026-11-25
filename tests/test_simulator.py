"""Tests d'integration: simulateur + client BACnet/IP sur loopback (127.0.0.1)."""

import asyncio
import socket
import unittest

from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.pdu import IPv4Address
from bacpypes3.primitivedata import ObjectIdentifier

from bacnet_simulator.client import _client_device
from bacnet_simulator.config import parse_config
from bacnet_simulator.simulator import BacnetSimulator


async def _next_present_value(scm, timeout: float = 2.0):
    """Lit les notifications COV jusqu'a trouver presentValue."""
    while True:
        prop_id, value = await asyncio.wait_for(scm.get_value(), timeout=timeout)
        if prop_id.attr == "presentValue":
            return value


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


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

    async def test_objects_support_cov(self) -> None:
        for _obj_cfg, obj in self.sim.objects:
            self.assertIsNotNone(getattr(obj, "_cov_criteria", None))

    async def test_cov_subscription_initial_notification(self) -> None:
        async with self.client.change_of_value(
            self.target, ObjectIdentifier("analogValue:1"), lifetime=60
        ) as scm:
            value = await _next_present_value(scm)
            self.assertAlmostEqual(float(value), 10.0)

    async def test_cov_subscription_on_animation(self) -> None:
        async with self.client.change_of_value(
            self.target,
            ObjectIdentifier("analogValue:2"),
            issue_confirmed_notifications=False,
            lifetime=60,
        ) as scm:
            values = [
                float(await _next_present_value(scm, timeout=3.0)) for _ in range(4)
            ]
            self.assertGreater(len(set(values)), 1)

    async def test_cov_subscription_on_write_binary(self) -> None:
        async with self.client.change_of_value(
            self.target,
            ObjectIdentifier("binaryValue:1"),
            issue_confirmed_notifications=False,
            lifetime=60,
        ) as scm:
            await _next_present_value(scm)
            await self.client.write_property(
                self.target, "binaryValue:1", "presentValue", "active"
            )
            value = await _next_present_value(scm)
            self.assertEqual(str(value), "active")

    async def test_cov_unsubscribe_stops_notifications(self) -> None:
        scm = self.client.change_of_value(
            self.target,
            ObjectIdentifier("analogValue:1"),
            issue_confirmed_notifications=False,
            lifetime=60,
        )
        async with scm:
            await _next_present_value(scm)
        while not scm.queue.empty():
            scm.queue.get_nowait()
        await self.client.write_property(
            self.target, "analogValue:1", "presentValue", 55.5
        )
        await asyncio.sleep(0.4)
        self.assertTrue(scm.queue.empty())


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

    def test_cov_increment_accepted_for_analog(self) -> None:
        cfg = parse_config(
            {
                "objects": [
                    {
                        "type": "analogValue",
                        "instance": 1,
                        "name": "a",
                        "cov_increment": 0.5,
                    }
                ]
            }
        )
        self.assertEqual(cfg.objects[0].cov_increment, 0.5)

    def test_cov_increment_rejected_when_negative(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {
                            "type": "analogValue",
                            "instance": 1,
                            "name": "a",
                            "cov_increment": -1.0,
                        }
                    ]
                }
            )

    def test_cov_increment_rejected_for_non_analog(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {
                            "type": "binaryValue",
                            "instance": 1,
                            "name": "b",
                            "cov_increment": 1.0,
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
