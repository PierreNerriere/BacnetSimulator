"""Interface web (bibliotheque standard uniquement) pour lire et modifier les valeurs.

Endpoints:
    GET  /                page HTML (le tableau est construit une seule fois ;
                          seules les cellules de valeur sont mises a jour en continu,
                          jamais les champs de saisie en cours d'edition)
    GET  /api/objects     liste JSON des objets, valeurs courantes et animations
    POST /api/set         body JSON {"id": "analogValue:1", "value": 42.5}
    POST /api/animation   body JSON {"id": "analogValue:1", "animation": {"type": "sine", ...}}
                          (animation null ou {"type": "none"} pour la desactiver)
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
  th, td { border: 1px solid #dde1e7; padding: .45rem .6rem; text-align: left; font-size: .92rem; vertical-align: top; }
  th { background: #eef1f5; }
  .id { color: #7a8494; font-size: .78rem; }
  input[type=number], input[type=text] { width: 7rem; padding: .25rem .4rem; }
  select { padding: .25rem .4rem; }
  button { padding: .3rem .8rem; cursor: pointer; }
  .ro { color: #7a8494; font-size: .85rem; }
  .params { margin-top: .3rem; display: flex; flex-wrap: wrap; gap: .4rem; align-items: center; }
  .params label { font-size: .8rem; color: #5a6675; }
  .animcell select { min-width: 6rem; }
</style>
</head>
<body>
<h1>Simulateur BACnet - valeurs des objets</h1>
<p id="device"></p>
<p id="status" class="ok"></p>
<p>
  <button onclick="reload()">Rafraichir</button>
  <label><input type="checkbox" id="autopoll" checked onchange="togglePoll()"> mise a jour auto des valeurs (2 s)</label>
</p>
<table id="objects">
  <thead>
    <tr><th>Objet</th><th>Type</th><th>Valeur actuelle</th><th>Nouvelle valeur</th><th>Animation</th></tr>
  </thead>
  <tbody></tbody>
</table>
<script>
const rows = {};
let animTypes = {};
let pollTimer = null;

const ANIM_PARAMS = {
  sine:   [['amplitude', 'number', 1.0], ['period', 'number', 60.0], ['offset', 'number', null]],
  ramp:   [['start', 'number', null], ['stop', 'number', null], ['duration', 'number', 60.0], ['loop', 'checkbox', false]],
  random: [['min', 'number', null], ['max', 'number', null]],
  step:   [['levels', 'text', null], ['duration', 'number', 10.0]],
  toggle: [['period', 'number', 10.0]],
  cycle:  [['period', 'number', 10.0]],
  none:   []
};

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

function renderAnimParams(container, type, params) {
  container.innerHTML = '';
  for (const [name, inputType, def] of (ANIM_PARAMS[type] || [])) {
    const label = document.createElement('label');
    label.textContent = name + ' ';
    const inp = document.createElement('input');
    inp.dataset.param = name;
    if (inputType === 'checkbox') {
      inp.type = 'checkbox';
      inp.checked = !!(params && params[name]);
    } else {
      inp.type = inputType;
      if (inputType === 'number') inp.step = 'any';
      const v = params && params[name] !== undefined ? params[name] : def;
      if (name === 'levels' && Array.isArray(v)) inp.value = v.join(',');
      else if (v !== null && v !== undefined) inp.value = v;
    }
    label.appendChild(inp);
    container.appendChild(label);
  }
}

function buildAnimCell(o) {
  const cell = document.createElement('td');
  cell.className = 'animcell';
  const sel = document.createElement('select');
  for (const t of (animTypes[o.kind] || ['none'])) {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    if (o.animation === t) opt.selected = true;
    sel.appendChild(opt);
  }
  const params = document.createElement('div');
  params.className = 'params';
  renderAnimParams(params, sel.value, o.animation_params);
  sel.onchange = () => renderAnimParams(params, sel.value, o.animation_params);
  const btn = document.createElement('button');
  btn.textContent = 'Appliquer';
  btn.onclick = () => applyAnimation(o, sel, params);
  cell.appendChild(sel);
  cell.appendChild(params);
  cell.appendChild(btn);
  return {cell, sel, params};
}

function collectAnimation(sel, params) {
  const animation = {type: sel.value};
  for (const inp of params.querySelectorAll('input[data-param]')) {
    const name = inp.dataset.param;
    if (inp.type === 'checkbox') {
      animation[name] = inp.checked;
    } else if (name === 'levels') {
      animation[name] = inp.value.split(',').map(s => parseFloat(s.trim())).filter(v => !isNaN(v));
    } else {
      const v = parseFloat(inp.value);
      if (!isNaN(v)) animation[name] = v;
    }
  }
  return animation;
}

async function applyAnimation(o, sel, params) {
  const animation = collectAnimation(sel, params);
  const res = await fetch('/api/animation', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id: o.id, animation: animation})
  });
  const body = await res.json();
  if (res.ok) {
    setStatus('animation de ' + o.id + ' = ' + body.object.animation, true);
    updateAnim(o.id, body.object);
  } else {
    setStatus('erreur: ' + (body.error || res.status), false);
  }
}

function updateAnim(id, o) {
  const row = rows[id];
  if (!row || row.cell.contains(document.activeElement)) return;
  row.sel.value = o.animation;
  renderAnimParams(row.params, o.animation, o.animation_params);
}

function buildRow(o) {
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

  const tdVal = document.createElement('td');
  tdVal.className = 'value-cell';
  tdVal.textContent = fmtValue(o);
  tr.appendChild(tdVal);

  const tdEdit = document.createElement('td');
  if (o.writable) {
    const editor = valueEditor(o);
    const btn = document.createElement('button');
    btn.textContent = 'Enregistrer';
    btn.onclick = async () => {
      const res = await fetch('/api/set', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: o.id, value: editor.value})
      });
      const body = await res.json();
      if (res.ok) {
        setStatus(o.id + ' = ' + fmtValue(body.object), true);
        updateValue(o.id, body.object);
        updateAnim(o.id, body.object);
      } else {
        setStatus('erreur: ' + (body.error || res.status), false);
      }
    };
    tdEdit.appendChild(editor);
    tdEdit.appendChild(document.createTextNode(' '));
    tdEdit.appendChild(btn);
  } else {
    tdEdit.className = 'ro';
    tdEdit.textContent = 'lecture seule';
  }
  tr.appendChild(tdEdit);

  const anim = buildAnimCell(o);
  tr.appendChild(anim.cell);

  rows[o.id] = {tr, valueCell: tdVal, cell: anim.cell, sel: anim.sel, params: anim.params};
  return tr;
}

function updateValue(id, o) {
  const row = rows[id];
  if (!row || row.tr.contains(document.activeElement)) return;
  row.valueCell.textContent = fmtValue(o);
}

async function reload() {
  try {
    const res = await fetch('/api/objects');
    const data = await res.json();
    document.getElementById('device').textContent =
      data.device.name + ' (device:' + data.device.instance + ')';
    animTypes = data.animations || {};
    const tbody = document.querySelector('#objects tbody');
    tbody.innerHTML = '';
    for (const id of Object.keys(rows)) delete rows[id];
    for (const o of data.objects) tbody.appendChild(buildRow(o));
  } catch (err) {
    setStatus('erreur de chargement: ' + err, false);
  }
}

async function pollValues() {
  try {
    const res = await fetch('/api/objects');
    const data = await res.json();
    for (const o of data.objects) {
      updateValue(o.id, o);
      updateAnim(o.id, o);
    }
  } catch (err) {
    setStatus('erreur de chargement: ' + err, false);
  }
}

function togglePoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  if (document.getElementById('autopoll').checked) pollTimer = setInterval(pollValues, 2000);
}

reload();
togglePoll();
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
        path = self._path()
        if path not in ("/api/set", "/api/animation"):
            self._send_json({"error": f"ressource inconnue: {path}"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("le body doit etre un objet JSON")
            if path == "/api/set":
                updated = self._sim.set_value(str(data.get("id", "")), data.get("value"))
            else:
                updated = self._sim.set_animation(
                    str(data.get("id", "")), data.get("animation")
                )
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
