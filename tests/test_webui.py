"""Tests de l'interface web: simulateur + HTTP sur loopback (127.0.0.1, ports ephemères)."""

import asyncio
import json
import socket
import unittest
import urllib.error
import urllib.request

from bacpypes3.ipv4.app import NormalApplication
from bacpypes3.pdu import IPv4Address

from bacnet_simulator.client import _client_device
from bacnet_simulator.config import parse_config
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
            "name": "WebTestDevice",
            "instance": 5679,
            "bind_address": f"127.0.0.1:{server_port}",
        },
        "update_interval": 0.1,
        "objects": [
            {
                "type": "analogInput",
                "instance": 1,
                "name": "AI-LectureSeule",
                "value": 7.0,
                "units": "degreesCelsius",
            },
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


class WebUITest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server_port = _free_port()
        self.client_port = _free_port()
        self.sim = BacnetSimulator(
            parse_config(_test_config(self.server_port)), web_address="127.0.0.1:0"
        )
        await self.sim.start()
        self.web_port = self.sim.web_port
        self.assertIsNotNone(self.web_port)
        self.base = f"http://127.0.0.1:{self.web_port}"
        self.client = NormalApplication(
            _client_device(), IPv4Address(f"127.0.0.1:{self.client_port}")
        )
        self.target = IPv4Address(f"127.0.0.1:{self.server_port}")
        await asyncio.sleep(0.1)

    async def asyncTearDown(self) -> None:
        self.client.close()
        await self.sim.stop()

    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=5) as resp:
            return resp.status, resp.read()

    def _post(self, path: str, payload: dict):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, json.loads(err.read())

    async def test_get_index_page(self) -> None:
        status, body = await asyncio.to_thread(self._get, "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body.lower())
        self.assertIn(b"/api/objects", body)
        self.assertIn(b"/api/animation", body)
        # le tableau n'est plus reconstruit automatiquement: seul le polling
        # des cellules de valeur existe, jamais un refresh complet de la page
        self.assertIn(b"pollValues", body)
        self.assertNotIn(b"setInterval(reload", body)

    async def test_list_objects(self) -> None:
        status, body = await asyncio.to_thread(self._get, "/api/objects")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["device"]["instance"], 5679)
        by_id = {o["id"]: o for o in data["objects"]}
        self.assertEqual(
            set(by_id),
            {
                "analogInput:1",
                "analogValue:1",
                "analogValue:2",
                "binaryValue:1",
                "multiStateValue:1",
            },
        )
        self.assertEqual(by_id["analogValue:1"]["value"], 10.0)
        self.assertTrue(by_id["analogValue:1"]["writable"])
        self.assertFalse(by_id["analogInput:1"]["writable"])
        self.assertEqual(by_id["analogValue:2"]["animation"], "sine")
        self.assertEqual(by_id["analogValue:2"]["animation_params"]["period"], 1.0)
        self.assertIsNone(by_id["analogValue:1"]["animation_params"])
        self.assertEqual(by_id["multiStateValue:1"]["state_text"], ["Off", "Auto", "Manual"])
        self.assertIn("analog", data["animations"])
        self.assertIn("sine", data["animations"]["analog"])
        self.assertIn("toggle", data["animations"]["binary"])
        self.assertIn("cycle", data["animations"]["multistate"])

    async def test_set_analog_value_visible_via_bacnet_and_animation_paused(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "analogValue:2", "value": 33.3}
        )
        self.assertEqual(status, 200)
        self.assertAlmostEqual(data["object"]["value"], 33.3)
        self.assertEqual(data["object"]["animation"], "none")

        value = await self.client.read_property(
            self.target, "analogValue:2", "presentValue"
        )
        self.assertAlmostEqual(float(value), 33.3, delta=1e-5)

        await asyncio.sleep(0.35)
        value = await self.client.read_property(
            self.target, "analogValue:2", "presentValue"
        )
        self.assertAlmostEqual(float(value), 33.3, delta=1e-5)

    async def test_set_binary_and_multistate(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "binaryValue:1", "value": "active"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["value"], "active")
        value = await self.client.read_property(
            self.target, "binaryValue:1", "presentValue"
        )
        self.assertEqual(str(value), "active")

        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "multiStateValue:1", "value": 3}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["value"], 3)
        value = await self.client.read_property(
            self.target, "multiStateValue:1", "presentValue"
        )
        self.assertEqual(int(value), 3)

    async def test_set_multistate_clamped_to_number_of_states(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "multiStateValue:1", "value": 99}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["value"], 3)

    async def test_set_unknown_object_returns_404(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "analogValue:99", "value": 1}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    async def test_set_readonly_object_rejected(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/set", {"id": "analogInput:1", "value": 5}
        )
        self.assertEqual(status, 400)
        self.assertIn("ecrivable", data["error"])

    async def test_set_invalid_value_rejected(self) -> None:
        status, _ = await asyncio.to_thread(
            self._post, "/api/set", {"id": "analogValue:1", "value": "abc"}
        )
        self.assertEqual(status, 400)
        status, _ = await asyncio.to_thread(
            self._post, "/api/set", {"id": "binaryValue:1", "value": "peut-etre"}
        )
        self.assertEqual(status, 400)
        status, _ = await asyncio.to_thread(
            self._post, "/api/set", {"id": "analogValue:1"}
        )
        self.assertEqual(status, 400)

    async def test_set_animation_then_value_animates_again(self) -> None:
        status, data = await asyncio.to_thread(
            self._post,
            "/api/animation",
            {
                "id": "analogValue:1",
                "animation": {"type": "sine", "amplitude": 5.0, "period": 1.0, "offset": 10.0},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["animation"], "sine")
        self.assertEqual(data["object"]["animation_params"]["amplitude"], 5.0)

        await asyncio.sleep(0.45)
        value = await self.client.read_property(
            self.target, "analogValue:1", "presentValue"
        )
        self.assertGreater(abs(float(value) - 10.0), 0.01)

        status, body = await asyncio.to_thread(self._get, "/api/objects")
        by_id = {o["id"]: o for o in json.loads(body)["objects"]}
        self.assertEqual(by_id["analogValue:1"]["animation"], "sine")

    async def test_disable_animation_via_none(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/animation", {"id": "analogValue:2", "animation": {"type": "none"}}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["animation"], "none")
        self.assertIsNone(data["object"]["animation_params"])

        value1 = await self.client.read_property(
            self.target, "analogValue:2", "presentValue"
        )
        await asyncio.sleep(0.35)
        value2 = await self.client.read_property(
            self.target, "analogValue:2", "presentValue"
        )
        self.assertAlmostEqual(float(value1), float(value2), delta=1e-5)

        status, data = await asyncio.to_thread(
            self._post, "/api/animation", {"id": "analogValue:2", "animation": None}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["animation"], "none")

    async def test_set_animation_binary_toggle(self) -> None:
        status, data = await asyncio.to_thread(
            self._post,
            "/api/animation",
            {"id": "binaryValue:1", "animation": {"type": "toggle", "period": 0.2}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["object"]["animation"], "toggle")

    async def test_set_animation_invalid_type_rejected(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/animation", {"id": "binaryValue:1", "animation": {"type": "sine"}}
        )
        self.assertEqual(status, 400)
        self.assertIn("incompatible", data["error"])

    async def test_set_animation_invalid_params_rejected(self) -> None:
        status, _ = await asyncio.to_thread(
            self._post,
            "/api/animation",
            {"id": "analogValue:1", "animation": {"type": "sine", "period": -5}},
        )
        self.assertEqual(status, 400)
        status, _ = await asyncio.to_thread(
            self._post,
            "/api/animation",
            {"id": "analogValue:1", "animation": {"type": "random", "min": 10, "max": 1}},
        )
        self.assertEqual(status, 400)
        status, _ = await asyncio.to_thread(
            self._post,
            "/api/animation",
            {"id": "analogValue:1", "animation": {"type": "step", "levels": []}},
        )
        self.assertEqual(status, 400)
        status, _ = await asyncio.to_thread(
            self._post, "/api/animation", {"id": "analogValue:1", "animation": "sine"}
        )
        self.assertEqual(status, 400)

    async def test_set_animation_unknown_object_returns_404(self) -> None:
        status, data = await asyncio.to_thread(
            self._post, "/api/animation", {"id": "analogValue:99", "animation": {"type": "sine"}}
        )
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    async def test_unknown_routes_return_404(self) -> None:
        def _get_404() -> int:
            try:
                with urllib.request.urlopen(self.base + "/nope", timeout=5) as resp:
                    return resp.status
            except urllib.error.HTTPError as err:
                return err.code

        status = await asyncio.to_thread(_get_404)
        self.assertEqual(status, 404)
        status, _ = await asyncio.to_thread(self._post, "/api/nope", {})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
