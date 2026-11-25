# BacnetSimulator

Simulateur de **device BACnet/IP** en Python, basé sur [bacpypes3](https://github.com/JoelBender/bacpypes3).

Le simulateur héberge un objet `Device` et une liste d'objets BACnet (AI, AO, AV, BI, BO, BV, MSV, MSO, MSV) dont les valeurs peuvent évoluer automatiquement (sinusoïde, rampe, aléatoire, bascule...). Il répond aux services usuels :

- **Who-Is / I-Am** (broadcast et unicast)
- **ReadProperty** / **ReadPropertyMultiple**
- **WriteProperty** / **WritePropertyMultiple** (les objets `*Value` et `*Output` sont écrivables, avec priorités pour les sorties)
- **SubscribeCOV** : notifications COV (confirmees ou non) envoyees a chaque changement de `presentValue` (animation ou ecriture externe) ; une notification initiale est envoyee des la souscription.

## Installation

Nécessite **Python >= 3.10** et [Poetry](https://python-poetry.org/) :

```bash
poetry install
```

Crée l'environnement virtuel et installe les dépendances verrouillées (`poetry.lock`). Les commandes `bacnet-simulator` et `bacnet-simulator-client` sont alors utilisables via `poetry run`, ou directement dans `poetry shell`.

Le port BACnet standard est **UDP 47808** (`0xBAC0`).

## Lancement rapide (démo)

```bash
poetry run bacnet-simulator
```

Lance un device `DemoDevice` (instance **1234**) sur `0.0.0.0:47808` avec 4 objets animés.

Dans un autre terminal, interrogez-le avec le client fourni :

```bash
poetry run bacnet-simulator-client --address 127.0.0.1:47808 list
poetry run bacnet-simulator-client --address 127.0.0.1:47808 read analogValue:1 presentValue
poetry run bacnet-simulator-client --address 127.0.0.1:47808 write analogValue:1 presentValue 42.5
poetry run bacnet-simulator-client --address 127.0.0.1:47808 who-is
```

## Lancement avec une configuration

```bash
poetry run bacnet-simulator --config examples/config.example.json
```

Options : `--address 0.0.0.0:47808`, `--instance 1234`, `--name MonDevice`, `-v` (debug).

### Format de la configuration JSON

```json
{
  "device": {
    "name": "MonDeviceSimule",
    "instance": 1234,
    "vendor_name": "VibeSim",
    "vendor_identifier": 999,
    "bind_address": "0.0.0.0:47808"
  },
  "update_interval": 1.0,
  "objects": [
    {
      "type": "analogValue",
      "instance": 1,
      "name": "AV-Temperature",
      "value": 21.0,
      "units": "degreesCelsius",
      "animation": { "type": "sine", "amplitude": 3.0, "period": 60.0, "offset": 21.0 },
      "cov_increment": 0.5
    }
  ]
}
```

- `device` : identité du device BACnet (`name`, `instance`, `vendor_*`, `bind_address` = adresse UDP d'écoute).
- `update_interval` : période (s) de recalcul des animations.
- `objects` : liste des objets BACnet.
- `cov_increment` (optionnel, objets analogiques uniquement) : variation minimale de `presentValue` declenchant une notification COV (`0.0` = notifier a chaque changement, defaut).

### Types d'objets supportés

| `type` | Écriture externe | Propriétés spécifiques |
|---|---|---|
| `analogInput` / `analogOutput` / `analogValue` | AV/AO oui | `value` (float), `units`, `cov_increment` |
| `binaryInput` / `binaryOutput` / `binaryValue` | BV/BO oui | `value` (`active`/`inactive`), `polarity` |
| `multiStateInput` / `multiStateOutput` / `multiStateValue` | MSV/MSO oui | `value` (1..N), `number_of_states`, `state_text` |

### Animations (`animation`)

- **Analogique** : `sine` (`amplitude`, `period`, `offset`), `ramp` (`start`, `stop`, `duration`, `loop`), `random` (`min`, `max`), `step` (`levels`, `duration`), ou `none`.
- **Binaire** : `toggle` (`period`), ou `none`.
- **Multi-états** : `cycle` (`period`), ou `none`.

## Client de test

```bash
poetry run bacnet-simulator-client --address <ip:port> who-is [--broadcast]
poetry run bacnet-simulator-client --address <ip:port> list [--device device:1234]
poetry run bacnet-simulator-client --address <ip:port> read analogValue:1 presentValue [--index N]
poetry run bacnet-simulator-client --address <ip:port> write analogValue:1 presentValue 42.5 [--priority 8]
poetry run bacnet-simulator-client --address <ip:port> subscribe analogValue:1 --count 3 [--unconfirmed] [--lifetime 60]
```

La commande `subscribe` affiche les notifications COV recues (valeur initiale immediate, puis a chaque changement) puis annule la souscription en sortant.

## Tests

```bash
poetry run python -m unittest discover -s tests -v
```

Les tests démarrent le simulateur et un client sur `127.0.0.1` (loopback, ports éphémères) et vérifient Who-Is, ReadProperty, WriteProperty, la liste d'objets et les souscriptions COV (notification initiale, notification sur changement, annulation).

## Notes réseau

- Sur un vrai réseau, le **Who-Is en broadcast** découvre le simulateur automatiquement (pensez à ouvrir l'UDP 47808 en entrée).
- En local/loopback, utilisez le mode unicast du client (`--address 127.0.0.1:47808`), car le broadcast ne traverse pas `127.0.0.1`.
- Plusieurs simulateurs sur la même machine : lancer chacun avec un `--address` différent (ex. `0.0.0.0:47809`).
