# BacnetSimulator

Simulateur de **device BACnet/IP** en Python, basé sur [bacpypes3](https://github.com/JoelBender/bacpypes3).

Le simulateur héberge un objet `Device` et une liste d'objets BACnet (AI, AO, AV, BI, BO, BV, MSV, MSO, MSV) dont les valeurs peuvent évoluer automatiquement (sinusoïde, rampe, aléatoire, bascule...). Il répond aux services usuels :

- **Who-Is / I-Am** (broadcast et unicast)
- **ReadProperty** / **ReadPropertyMultiple**
- **WriteProperty** / **WritePropertyMultiple** (les objets `*Value` et `*Output` sont écrivables, avec priorités pour les sorties)
- **SubscribeCOV** : notifications COV (confirmees ou non) envoyees a chaque changement de `presentValue` (animation ou ecriture externe) ; une notification initiale est envoyee des la souscription.
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

Options : `--address 0.0.0.0:47808`, `--instance 1234`, `--name MonDevice`, `--web` / `--web-address 127.0.0.1:8080`, `-v` (debug).

## Interface web

L'option `--web` lance en plus une **interface web** pour visualiser et modifier les valeurs des objets (bibliothèque standard uniquement, aucune dépendance supplémentaire) :

```bash
poetry run bacnet-simulator --web                       # http://127.0.0.1:8080
poetry run bacnet-simulator --config examples/config.example.json --web --web-address 127.0.0.1:8080
```

- Par défaut l'interface n'écoute que sur **loopback** (`127.0.0.1:8080`) ; `--web-address 0.0.0.0:8080` l'expose sur le réseau (pensez au pare-feu).
- La page `GET /` liste les objets avec leur valeur courante et un formulaire par objet `*Value` / `*Output` (les `*Input` sont en lecture seule, comme en BACnet). **La page n'est jamais reconstruite automatiquement** : seules les cellules « Valeur actuelle » sont mises à jour toutes les 2 s (case « mise à jour auto » pour désactiver), et la ligne en cours de saisie est toujours ignorée — on peut donc taper une valeur sans perdre le focus. Le bouton « Rafraîchir » recharge la page à la demande.
- **Modifier une valeur depuis la page désactive l'animation** de l'objet concerné, pour que la valeur saisie soit conservée (visible aussi via `ReadProperty`).
- **Choisir l'animation depuis la page** : chaque ligne a un sélecteur d'animation (`none`, `sine`, `ramp`, `random`, `step` pour les analogiques ; `none`, `toggle` pour les binaires ; `none`, `cycle` pour les multi-états) avec ses paramètres (période, amplitude, niveaux...) et un bouton « Appliquer ».
- Les valeurs **analogiques sont affichées avec 1 chiffre après la virgule** (le champ de saisie conserve la précision complète).

API JSON :

| Endpoint | Description |
|---|---|
| `GET /api/objects` | liste JSON des objets (id, nom, type, valeur, unités, `animation`, `animation_params`, `writable`) + les animations autorisées par genre (`animations`) |
| `POST /api/set` | body `{"id": "analogValue:1", "value": 42.5}` → modifie la valeur, réponse `{"object": {...}}` |
| `POST /api/animation` | body `{"id": "analogValue:1", "animation": {"type": "sine", "amplitude": 3, "period": 60, "offset": 21}}` → choisit l'animation (`null` ou `{"type": "none"}` pour la désactiver), réponse `{"object": {...}}` |

Exemple :

```bash
python3 - <<'EOF'
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8080/api/set",
    data=json.dumps({"id": "analogValue:1", "value": 42.5}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
EOF
```

Valeurs acceptées : nombre (analogique), `active`/`inactive` (binaire), entier 1..N (multi-états, borné automatiquement). Erreurs : `404` objet inconnu, `400` valeur/animation invalide ou objet non écrivable.

Exemple de changement d'animation :

```bash
python3 - <<'EOF'
import json, urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8080/api/animation",
    data=json.dumps({"id": "analogValue:1", "animation": {"type": "random", "min": 18, "max": 26}}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
print(urllib.request.urlopen(req).read().decode())
EOF
```
Options : `--address 0.0.0.0:47808`, `--broadcast-address 192.168.1.255`, `--instance 1234`, `--name MonDevice`, `-v` (debug).

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
    "bind_address": "0.0.0.0:47808",
    "broadcast_address": "192.168.1.255"
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

- `device` : identité du device BACnet (`name`, `instance`, `vendor_*`, `bind_address` = adresse UDP d'écoute, `broadcast_address` = adresse de broadcast IPv4 optionnelle, ex. `192.168.1.255` ou `255.255.255.255[:47808]`).
- `update_interval` : période (s) de recalcul des animations.
- `objects` : liste des objets BACnet.
- `cov_increment` (optionnel, objets analogiques uniquement) : variation minimale de `presentValue` declenchant une notification COV (`0.0` = notifier a chaque changement, defaut).
- `bbmd` : section BBMD (voir ci-dessous) : `enabled` (booléen) et `peers` (liste d'adresses `ip:port` des autres BBMD, = BDT initiale).

### Types d'objets supportés

| `type` | Écriture externe | Propriétés spécifiques |
|---|---|---|
| `analogInput` / `analogOutput` / `analogValue` | AV/AO oui | `value` (float), `units`, `cov_increment` |
| `binaryInput` / `binaryOutput` / `binaryValue` | BV/BO oui | `value` (`active`/`inactive`), `polarity` |
| `analogInput` / `analogOutput` / `analogValue` | AV/AO oui | `value` (float), `units` |
| `binaryInput` / `binaryOutput` / `binaryValue` | BV/BO oui | `value` (voir énumérations ci-dessous), `polarity`, `active_text` / `inactive_text` |
| `multiStateInput` / `multiStateOutput` / `multiStateValue` | MSV/MSO oui | `value` (1..N), `number_of_states`, `state_text` |

### Énumérations

Les valeurs énumérées acceptent les libellés canoniques BACnet **et** des alias français/anglais, en majuscules ou non :

- **Binaire** (`presentValue` des BI/BO/BV, `value` en config, écriture client) : `active`/`inactive` ainsi que `actif`/`inactif`, `on`/`off`, `oui`/`non`, `marche`/`arret`, `true`/`false`, `1`/`0` (aussi booléens/nombres en config).
- **Polarité** (`polarity` des BI/BO) : `normal`/`reverse`, alias `inverse`/`inversée`/`reversed`.

Les objets binaires exposent de plus les libellés `activeText` / `inactiveText` (ex. `Actif` / `Inactif` par défaut), configurables via `active_text` / `inactive_text` :

```json
{
  "type": "binaryValue",
  "instance": 1,
  "name": "BV-Pompe",
  "value": "inactif",
  "active_text": "Marche",
  "inactive_text": "Arret"
}
```

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
poetry run bacnet-simulator-client --address <ip:port> subscribe analogValue:1 --count 3 [--unconfirmed] [--lifetime 60]
poetry run bacnet-simulator-client --address <ip:port> write binaryValue:1 presentValue actif
poetry run bacnet-simulator-client --address <ip:port> read binaryValue:1 activeText
poetry run bacnet-simulator-client --address <bbmd:port> read-bdt   # BDT du BBMD
poetry run bacnet-simulator-client --address <bbmd:port> read-fdt   # FDT du BBMD
```

La commande `subscribe` affiche les notifications COV recues (valeur initiale immediate, puis a chaque changement) puis annule la souscription en sortant.

## Tests

```bash
poetry run python -m unittest discover -s tests -v
```

Les tests démarrent le simulateur et un client sur `127.0.0.1` (loopback, ports éphémères) et vérifient Who-Is, ReadProperty, WriteProperty, la liste d'objets et les souscriptions COV (notification initiale, notification sur changement, annulation).

## Notes réseau

- Sur un vrai réseau, le **Who-Is en broadcast** découvre le simulateur automatiquement (pensez à ouvrir l'UDP 47808 en entrée). L'adresse de broadcast est détectée automatiquement depuis l'interface principale quand `bind_address` est joker (`0.0.0.0`) ; on peut la forcer avec `broadcast_address` dans la configuration ou `--broadcast-address` en ligne de commande (repli sur `255.255.255.255` si la détection échoue). Sans adresse de broadcast, bacpypes3 journalise `RuntimeError('no broadcast')` lors des envois en broadcast (ex. réponse I-Am à un Who-Is broadcast).
- En local/loopback, utilisez le mode unicast du client (`--address 127.0.0.1:47808`), car le broadcast ne traverse pas `127.0.0.1` (aucun broadcast n'est détecté sur `127.0.0.0/8`).
- Plusieurs simulateurs sur la même machine : lancer chacun avec un `--address` différent (ex. `0.0.0.0:47809`).
