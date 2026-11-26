"""Interface web (bibliotheque standard uniquement) pour lire et modifier les valeurs.

Endpoints:
    GET  /              page HTML (rafraichie automatiquement toutes les 2 s)
    GET  /api/objects   liste JSON des objets et de leurs valeurs courantes
    POST /api/set       body JSON {"id": "analogValue:1", "value": 42.5}
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Tuple

_log = logging.getLogger("bacnet_simulator.web")

_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BacnetSimulator - valeurs</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem; background: #f6f7f9; color: #1c2430; }
  h1 { font-size: 1.3rem; margin-bottom: 0.2rem; }
  #device { color: #5a6675; margin-top: 0; }
  #status { min-height: 1.2em; font-weight: 600; }
  #status.ok { color: #1a7f37; }
  #status.ko { color: #b3261e; }
  table { border-collapse: collapse; background: #fff; width: 100%; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
  th, td { border: 1px solid #dde1e7; padding: .45rem .6rem; text-align: left; font-size: .92rem; }
  th { background: #eef1f5; }
  .id { color: #7a8494; font-size: .78rem; }
  input[type=number] { width: 9rem; padding: .25rem .4rem; }
  select { padding: .25rem .4rem; }
  button { padding: .3rem .8rem; cursor: pointer; }
  .ro { color: #7a8494; font-size: .85rem; }
</style>
</head>
<body>
<h1>Simulateur BACnet - valeurs des objets</h1>
<p id="device"></p>
<p id="status" class="ok"></p>
<table id="objects">
  <thead>
    <tr><th>Objet</th><th>Type</th><th>Animation</th><th>Valeur actuelle</th><th>Nouvelle valeur</th><th></th></tr>
  </thead>
  <tbody></tbody>
</table>
<p><button onclick="refresh()">Rafraichir</button></p>
<script>
function setStatus(msg, ok) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = ok ? 'ok' : 'ko';
}

function fmtValue(o) {
  if (o.kind === 'binary') return o.value;
  if (o.kind === 'multistate') {
    const label = (o.state_text && o.state_text[o.value - 1]) || ('State ' + o.value);
    return o.value + ' - ' + label;
  }
  return o.units ? o.value + ' ' + o.units : String(o.value);
}

function valueEditor(o) {
  if (o.kind === 'binary') {
    const sel = document.createElement('select');
    for (const s of ['inactive', 'active']) {
      const opt = document.createElement('option');
      opt.value = s;
      opt.textContent = s;
      if (o.value === s) opt.selected = true;
      sel.appendChild(opt);
    }
    return sel;
  }
  if (o.kind === 'multistate') {
    const sel = document.createElement('select');
    const n = o.number_of_states || 2;
    for (let i = 1; i <= n; i++) {
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = (o.state_text && o.state_text[i - 1]) ? i + ' - ' + o.state_text[i - 1] : 'State ' + i;
      if (o.value === i) opt.selected = true;
      sel.appendChild(opt);
    }
    return sel;
  }
  const inp = document.createElement('input');
  inp.type = 'number';
  inp.step = 'any';
  inp.value = o.value;
  return inp;
}

async function refresh() {
  try {
    const res = await fetch('/api/objects');
    const data = await res.json();
    document.getElementById('device').textContent =
      data.device.name + ' (device:' + data.device.instance + ')';
    const tbody = document.querySelector('#objects tbody');
    tbody.innerHTML = '';
    for (const o of data.objects) {
      const tr = document.createElement('tr');

      const tdName = document.createElement('td');
      tdName.textContent = o.name;
      const id = document.createElement('div');
      id.className = 'id';
      id.textContent = o.id;
      tdName.appendChild(id);
      tr.appendChild(tdName);

      const tdType = document.createElement('td');
      tdType.textContent = o.type;
      tr.appendChild(tdType);

      const tdAnim = document.createElement('td');
      tdAnim.textContent = o.animation;
      tr.appendChild(tdAnim);

      const tdVal = document.createElement('td');
      tdVal.textContent = fmtValue(o);
      tr.appendChild(tdVal);

      const tdEdit = document.createElement('td');
      const editor = o.writable ? valueEditor(o) : document.createElement('span');
      tdEdit.appendChild(editor);
      tr.appendChild(tdEdit);

      const tdBtn = document.createElement('td');
      if (o.writable) {
        const btn = document.createElement('button');
        btn.textContent = 'Enregistrer';
        btn.onclick = async () => {
          const r = await fetch('/api/set', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({id: o.id, value: editor.value})
          });
          const body = await r.json();
          if (r.ok) {
            setStatus(o.id + ' = ' + fmtValue(body.object), true);
          } else {
            setStatus('erreur: ' + (body.error || r.status), false);
          }
          await refresh();
        };
        tdBtn.appendChild(btn);
      } else {
        tdBtn.className = 'ro';
        tdBtn.textContent = 'lecture seule';
      }
      tr.appendChild(tdBtn);

      tbody.appendChild(tr);
    }
  } catch (err) {
    setStatus('erreur de chargement: ' + err, false);
  }
}

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "BacnetSimulatorWeb/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        _log.debug("%s - %s", self.address_string(), fmt % args)

    @property
    def _sim(self) -> Any:
        return self.server.simulator

    def _path(self) -> str:
        return self.path.split("?", 1)[0]

    def _send(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        self._send(
            json.dumps(payload).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def do_GET(self) -> None:
        path = self._path()
        if path == "/":
            self._send(_PAGE.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/objects":
            self._send_json(self._sim.describe())
        else:
            self._send_json({"error": f"ressource inconnue: {path}"}, 404)

    def do_POST(self) -> None:
        if self._path() != "/api/set":
            self._send_json({"error": f"ressource inconnue: {self._path()}"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("le body doit etre un objet JSON")
            updated = self._sim.set_value(str(data.get("id", "")), data.get("value"))
        except KeyError as err:
            self._send_json({"error": f"objet inconnu: {err.args[0]!r}"}, 404)
            return
        except ValueError as err:
            self._send_json({"error": str(err)}, 400)
            return
        self._send_json({"object": updated})


class WebUI:
    """Serveur HTTP annexe (thread dedie) exposant le simulateur."""

    def __init__(self, simulator: Any, host: str, port: int) -> None:
        self.simulator = simulator
        self.server = ThreadingHTTPServer((host, port), _RequestHandler)
        self.server.simulator = simulator
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            name="bacnet-simulator-web",
            daemon=True,
        )

    @property
    def address(self) -> Tuple[str, int]:
        host, port = self.server.server_address[:2]
        return host, port

    def start(self) -> None:
        self._thread.start()
        _log.info("interface web disponible sur http://%s:%d/", *self.address)

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self._thread.join(timeout=5.0)
