# BacnetSimulator

Simulateur de **device BACnet/IP** en Python, basé sur [bacpypes3](https://github.com/JoelBender/bacpypes3).

Le simulateur héberge un objet `Device` et une liste d'objets BACnet (AI, AO, AV, BI, BO, BV, MSV, MSO, MSV) dont les valeurs peuvent évoluer automatiquement (sinusoïde, rampe, aléatoire, bascule...). Il répond aux services usuels :

- **Who-Is / I-Am** (broadcast et unicast)
- **ReadProperty** / **ReadPropertyMultiple**
- **WriteProperty** / **WritePropertyMultiple** (les objets `*Value` et `*Output` sont écrivables, avec priorités pour les sorties)
- **BBMD** (Annex J) en option : table de distribution de broadcast (BDT), table de devices étrangers (FDT) et transfert des broadcasts entre sous-réseaux

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

### Exemple : liste de points de supervision (PTU)

`examples/config.ptu.json` traduit une liste de points de supervision de régulateur PTU (défaut de communication, commande d'occupation, commandes et positions de stores, défauts d'éclairage et de modules) :

```bash
poetry run bacnet-simulator --config examples/config.ptu.json
```

| Composant | Objet | objectName |
|---|---|---|
| Communication | `binaryValue:50` | `Defaut_Com_PTU` |
| CdeOccupation | `multiStateValue:201` | `OccupancyCmd` |
| CdeStoresNord / Sud / Est / Ouest | `analogValue:201` à `204` | `BlindTranslationCmdNord/Sud/Est/Ouest` |
| PosStoresOcc / PosStoresInocc | `analogValue:205` / `206` | `TranslationOcc` / `TranslationUnocc` |
| E1, E2, S3, S4 | `binaryValue:51` à `54` | `Defaut_ECL1`, `Defaut_ECL2`, `Defaut_BLI1`, `Defaut_BLI2` |
| U1, UCH1, SC1 | `binaryValue:41` | `Defaut_RC1` |
| SC2, M3, M4, M5 | `binaryValue:42` à `45` | `Defaut_RC2` à `Defaut_RC5` |

Notes :

- Objets binaires (TA) : `inactive` = état 0 (Normal), `active` = état 1 (Défaut).
- `multiStateValue:201` : états 1 à 4 = Occupé, Inoccupé, Bypass, Standby.
- Les objets `analogValue` et `multiStateValue` (TR, L/E) sont écrivables depuis la supervision.
- Les lignes « Suppression » de la liste source (SA2, M6) ne sont pas reprises ; les composants partageant le même point `binaryValue:41` (U1, UCH1, SC1) sont fusionnés en un seul objet, le simulateur interdisant les doublons type+instance.

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
      "animation": { "type": "sine", "amplitude": 3.0, "period": 60.0, "offset": 21.0 }
    }
  ]
}
```

- `device` : identité du device BACnet (`name`, `instance`, `vendor_*`, `bind_address` = adresse UDP d'écoute).
- `update_interval` : période (s) de recalcul des animations.
- `objects` : liste des objets BACnet.
- `bbmd` : section BBMD (voir ci-dessous) : `enabled` (booléen) et `peers` (liste d'adresses `ip:port` des autres BBMD, = BDT initiale).

### Types d'objets supportés

| `type` | Écriture externe | Propriétés spécifiques |
|---|---|---|
| `analogInput` / `analogOutput` / `analogValue` | AV/AO oui | `value` (float), `units` |
| `binaryInput` / `binaryOutput` / `binaryValue` | BV/BO oui | `value` (`active`/`inactive`), `polarity` |
| `multiStateInput` / `multiStateOutput` / `multiStateValue` | MSV/MSO oui | `value` (1..N), `number_of_states`, `state_text` |

### Animations (`animation`)

- **Analogique** : `sine` (`amplitude`, `period`, `offset`), `ramp` (`start`, `stop`, `duration`, `loop`), `random` (`min`, `max`), `step` (`levels`, `duration`), ou `none`.
- **Binaire** : `toggle` (`period`), ou `none`.
- **Multi-états** : `cycle` (`period`), ou `none`.

## Mode BBMD (Annex J)

En mode **BBMD** (*BACnet Broadcast Management Device*), le simulateur joue le rôle d'un BBMD BACnet/IP :

- il tient une **BDT** (*Broadcast Distribution Table*) : chaque broadcast reçu est retransmis à tous les peers de la BDT (et à la FDT) sous forme de `Forwarded-NPDU` ;
- il tient une **FDT** (*Foreign Device Table*) : les devices des autres sous-réseaux s'y enregistrent avec *Register-Foreign-Device* et reçoivent alors les broadcasts transferés ;
- il répond aux fonctions BVLL *Read/Write-Broadcast-Distribution-Table* et *Read/Delete-Foreign-Device-Table*.

La BDT initiale se définit dans la configuration :

```json
"bbmd": {
  "enabled": true,
  "peers": ["0.0.0.0:47808", "10.0.1.2:47808"]
}
```

(voir `examples/config.bbmd.example.json`). Par convention, la BDT contient le BBMD lui-même (`0.0.0.0:47808` ici = adresse locale).

En ligne de commande (sans fichier de config) :

```bash
poetry run bacnet-simulator --bbmd --bbmd-peer 10.0.1.2:47808 --bbmd-peer 10.0.2.2:47808
```

`--bbmd` active le mode avec les peers du fichier de config ; `--bbmd-peer IP:PORT` (répétable) active le mode et remplace la BDT par les peers donnés.

Pour inspecter un BBMD depuis le client :

```bash
poetry run bacnet-simulator-client --address <bbmd:47808> read-bdt
poetry run bacnet-simulator-client --address <bbmd:47808> read-fdt
```

## Client de test

```bash
poetry run bacnet-simulator-client --address <ip:port> who-is [--broadcast]
poetry run bacnet-simulator-client --address <ip:port> list [--device device:1234]
poetry run bacnet-simulator-client --address <ip:port> read analogValue:1 presentValue [--index N]
poetry run bacnet-simulator-client --address <ip:port> write analogValue:1 presentValue 42.5 [--priority 8]
poetry run bacnet-simulator-client --address <bbmd:port> read-bdt   # BDT du BBMD
poetry run bacnet-simulator-client --address <bbmd:port> read-fdt   # FDT du BBMD
```

## Tests

```bash
poetry run python -m unittest discover -s tests -v
```

Les tests démarrent le simulateur et un client sur `127.0.0.1` (loopback, ports éphémères) et vérifient Who-Is, ReadProperty, WriteProperty, la liste d'objets et les animations.

## Notes réseau

- Sur un vrai réseau, le **Who-Is en broadcast** découvre le simulateur automatiquement (pensez à ouvrir l'UDP 47808 en entrée).
- En local/loopback, utilisez le mode unicast du client (`--address 127.0.0.1:47808`), car le broadcast ne traverse pas `127.0.0.1`.
- Plusieurs simulateurs sur la même machine : lancer chacun avec un `--address` différent (ex. `0.0.0.0:47809`).
