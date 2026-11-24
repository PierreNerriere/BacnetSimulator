"""Tests d'integration: simulateur + client BACnet/IP sur loopback (127.0.0.1)."""

import asyncio
import socket
import unittest

from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.pdu import IPv4Address

from bacnet_simulator.client import _cast_write_value, _client_device
from bacnet_simulator.config import parse_config
from bacnet_simulator.enums import cast_binary, cast_polarity
from bacnet_simulator.objects import build_object
from bacnet_simulator.simulator import BacnetSimulator


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
                "value": "inactif",
                "active_text": "Actif",
                "inactive_text": "Inactif",
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

    async def test_write_binary_value_french_alias(self) -> None:
        await self.client.write_property(
            self.target,
            "binaryValue:1",
            "presentValue",
            _cast_write_value("Actif", "binaryValue", "presentValue"),
        )
        value = await self.client.read_property(self.target, "binaryValue:1", "presentValue")
        self.assertEqual(str(value), "active")

    async def test_binary_active_inactive_text(self) -> None:
        active = await self.client.read_property(self.target, "binaryValue:1", "activeText")
        inactive = await self.client.read_property(self.target, "binaryValue:1", "inactiveText")
        self.assertEqual(str(active), "Actif")
        self.assertEqual(str(inactive), "Inactif")

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

    def test_binary_value_alias_normalized(self) -> None:
        cfg = parse_config(
            {"objects": [{"type": "binaryValue", "instance": 1, "name": "b", "value": "Actif"}]}
        )
        self.assertEqual(cfg.objects[0].value, "active")

    def test_invalid_binary_value_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {"objects": [{"type": "binaryValue", "instance": 1, "name": "b", "value": "peut-etre"}]}
            )

    def test_polarity_alias_normalized(self) -> None:
        cfg = parse_config(
            {"objects": [{"type": "binaryInput", "instance": 1, "name": "b", "polarity": "Inverse"}]}
        )
        self.assertEqual(cfg.objects[0].polarity, "reverse")

    def test_invalid_polarity_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {"objects": [{"type": "binaryInput", "instance": 1, "name": "b", "polarity": "cote"}]}
            )

    def test_active_text_only_on_binary(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {"objects": [{"type": "analogValue", "instance": 1, "name": "a", "active_text": "Actif"}]}
            )

    def test_empty_active_text_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {"objects": [{"type": "binaryValue", "instance": 1, "name": "b", "active_text": "  "}]}
            )

    def test_state_text_length_must_match_states(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {
                            "type": "multiStateValue",
                            "instance": 1,
                            "name": "m",
                            "number_of_states": 3,
                            "state_text": ["Arret", "Auto"],
                        }
                    ]
                }
            )

    def test_multistate_value_out_of_range_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_config(
                {
                    "objects": [
                        {
                            "type": "multiStateValue",
                            "instance": 1,
                            "name": "m",
                            "number_of_states": 3,
                            "value": 9,
                        }
                    ]
                }
            )

    def test_default_binary_texts(self) -> None:
        cfg = parse_config({"objects": [{"type": "binaryValue", "instance": 1, "name": "b"}]})
        obj = build_object(cfg.objects[0])
        self.assertEqual(str(obj.activeText), "Actif")
        self.assertEqual(str(obj.inactiveText), "Inactif")


class EnumCastTest(unittest.TestCase):
    def test_cast_binary_active_aliases(self) -> None:
        for value in ("active", "Actif", " ACTIF ", "on", "oui", "marche", "true", "1", 1, 2.0, True):
            self.assertEqual(cast_binary(value), "active", msg=repr(value))

    def test_cast_binary_inactive_aliases(self) -> None:
        for value in ("inactive", "Inactif", "off", "non", "arret", "false", "0", 0, 0.0, False):
            self.assertEqual(cast_binary(value), "inactive", msg=repr(value))

    def test_cast_binary_invalid(self) -> None:
        for value in ("peut-etre", "", None, [1]):
            with self.assertRaises(ValueError, msg=repr(value)):
                cast_binary(value)

    def test_cast_polarity(self) -> None:
        self.assertEqual(cast_polarity("normal"), "normal")
        self.assertEqual(cast_polarity("NORMAL"), "normal")
        for value in ("reverse", "reversed", "inverse", "Inversee"):
            self.assertEqual(cast_polarity(value), "reverse", msg=repr(value))
        with self.assertRaises(ValueError):
            cast_polarity("cote")

    def test_client_cast_write_value(self) -> None:
        self.assertEqual(_cast_write_value("actif", "binaryValue", "presentValue"), "active")
        self.assertEqual(_cast_write_value("0", "binaryOutput", "presentValue"), "inactive")
        self.assertEqual(_cast_write_value("2", "multiStateValue", "presentValue"), 2)
        self.assertEqual(_cast_write_value("inverse", "binaryInput", "polarity"), "reverse")
        self.assertAlmostEqual(_cast_write_value("42.5", "analogValue", "presentValue"), 42.5)
        self.assertIs(_cast_write_value("true", "analogValue", "presentValue"), True)
        with self.assertRaises(ValueError):
            _cast_write_value("abc", "multiStateValue", "presentValue")


if __name__ == "__main__":
    unittest.main()
