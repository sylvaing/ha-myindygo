# MyIndygo (Solem) pour Home Assistant

> **Projet non officiel.** Ni affilié à Solem, ni approuvé ou supporté par Solem.
> « MyIndygo » et « Solem » sont des marques de leurs propriétaires respectifs.
> L'icône de l'intégration est une création originale (un symbole de piscine générique), pas un logo
> Solem ou MyIndygo.

🇬🇧 [English version](README.md)

Intégration personnalisée Home Assistant pour les équipements de piscine **Solem MyIndygo**, qui utilise la
même API cloud que l'application mobile MyIndygo.

La version 0.1.0 est en lecture seule. La prochaine version ajoute les commandes manuelles des sorties du
coffret (marche forcée, boost, pause, arrêt, voir [Actions](#actions)) ; les programmes et les consignes
de l'électrolyseur sont sur la [feuille de route](https://github.com/sylvaing/ha-myindygo/milestones).

## Prérequis

- Home Assistant 2026.11 ou plus récent
- Un compte MyIndygo (e-mail et mot de passe de l'application mobile) avec des équipements joignables par
  une passerelle MyIndygo

## Équipements pris en charge

Développé et testé avec :

| Appareil | Rôle |
|---|---|
| LR-MB-10 | passerelle LoRa (Wi-Fi) |
| LR-PC | coffret piscine : pompe de filtration, 2 sorties auxiliaires, température de l'eau |
| IPX (PoolTech) | interface vers un électrolyseur au sel avec régulation pH |

D'autres équipements MyIndygo peuvent fonctionner en partie mais ne sont pas testés. Les retours et les
diagnostics sont les bienvenus.

## Installation

### Avec HACS (recommandé)

1. Dans HACS, ouvrez le menu ⋮ → **Dépôts personnalisés**.
2. Ajoutez `https://github.com/sylvaing/ha-myindygo` avec le type **Intégration**.
3. Cherchez **MyIndygo (Solem)**, téléchargez-la, puis redémarrez Home Assistant.

### Manuellement

Copiez `custom_components/myindygo` dans le dossier `custom_components` de votre configuration Home
Assistant, puis redémarrez Home Assistant.

## Configuration

**Paramètres → Appareils et services → Ajouter une intégration → MyIndygo (Solem)**, puis saisissez l'e-mail
et le mot de passe de votre compte de l'application MyIndygo. Un appareil est créé par module : passerelle →
coffret → électrolyseur.

Options (**Configurer** sur l'intégration) :

| Option | Par défaut | Plage |
|---|---|---|
| Intervalle de l'état du coffret | 2 min | 1–30 min |
| Intervalle des données cloud | 15 min | 10–60 min |
| Identifiant client de l'application (avancé) | intégré | à laisser vide, sauf si l'identifiant de l'application change |

Gardez des intervalles prudents : le cloud MyIndygo n'est pas prévu pour des interrogations fréquentes.

## Entités

### Coffret (LR-PC)

| Entité | Remarques |
|---|---|
| Température de l'eau | °C |
| Filtration, Sortie 1, Sortie 2 | marche / arrêt |
| État de la filtration / de la sortie | arrêt, programme, marche forcée, boost, hors-gel, pause |
| Temps restant | minutes |
| Mode | arrêt, marche, auto |
| Tranche de température | tranche utilisée par le programme selon la température, par ex. `18-20 °C` |
| Filtration prévue aujourd'hui | heures, décodées du planning du coffret |
| Diagnostics | dernière communication, commande radio en attente, alerte d'entrée, règle et type des sorties, température du coffret (désactivée par défaut) |

### Électrolyseur (IPX PoolTech)

| Entité | Remarques |
|---|---|
| pH, consigne pH, régulation pH | |
| Redox | seulement si une sonde redox est installée |
| Sel | g/L |
| Consigne de production, mode d'électrolyse | %, arrêt / pourcentage / auto |
| Boost, temps de boost restant | |
| Production, injection pH, hivernage | |
| Alarme | les textes des alarmes sont dans l'attribut `alarms` |
| Diagnostics | heures d'électrolyse, tension de la cellule, dernière remontée ; entrées débit, volet, bidon pH et commande externe (désactivées par défaut) |

L'électrolyseur ne remonte ses données que pendant la filtration, environ toutes les 10 à 15 minutes :
l'entité **Dernière remontée** indique l'âge de ses valeurs.

### Passerelle (LR-MB-10)

Connexion au cloud ; diagnostics : liaison Wi-Fi, dernier redémarrage, code de réinitialisation (désactivé
par défaut).

## Actions

Les sorties du coffret acceptent les mêmes commandes manuelles que l'application MyIndygo. Chaque action
cible le capteur binaire de marche d'une sortie (**Filtration**, **Sortie 1**, **Sortie 2**), ou
l'appareil coffret pour atteindre toutes ses sorties :

| Action | Paramètre | Effet |
|---|---|---|
| `myindygo.start_manual_run` | durée (1 min – 24 h) | met la sortie en marche, puis la rend à son programme |
| `myindygo.start_boost` | durée (1 min – 24 h) | boost de la sortie filtration ou traitement |
| `myindygo.pause` | jours (1 – 30) | arrête la sortie, programme compris |
| `myindygo.stop_manual_command` | — | termine la marche forcée, le boost ou la pause |

```yaml
action: myindygo.start_manual_run
target:
  entity_id: binary_sensor.lrpc_xxxxxx_filtration
data:
  duration: "01:30:00"
```

À savoir :

- Le coffret **ignore sans erreur** une commande manuelle sur une sortie qui n'est pas en mode **Auto**
  (voir le capteur *mode*). L'intégration refuse alors l'action avec une erreur plutôt que de faire
  semblant ; changez d'abord le mode dans l'application MyIndygo. Le boost n'est proposé que pour les
  sorties filtration et traitement, comme dans l'application.
- Le cloud répond avant l'échange radio avec le coffret (**Commande radio en attente** est alors
  allumé). L'intégration relit l'état 10 secondes plus tard et journalise un avertissement si la
  commande n'a eu aucun effet visible.
- Une sortie auxiliaire réglée pour forcer la filtration est commandée seule (l'application prolonge
  aussi la filtration dans ce cas) ; les pompes à vitesse variable ne sont pas prises en charge.

## Fonctionnement

L'intégration interroge le cloud MyIndygo (`myindygo.com`) comme l'application mobile :

- toutes les 2 minutes, l'état temps réel du coffret, lu à travers la passerelle ;
- toutes les 15 minutes, les modules (dont les données de l'électrolyseur), les mesures de la piscine et
  les programmes.

Une coupure courte de la passerelle conserve le dernier état du coffret pendant 6 minutes environ.

## Dépannage

Téléchargez les diagnostics depuis la page de l'intégration (⋮ → **Télécharger les diagnostics**) et
joignez-les à une [issue](https://github.com/sylvaing/ha-myindygo/issues). Les données personnelles
(e-mail, adresse, localisation, numéros de série, adresses MAC, jetons) en sont retirées. Ne publiez jamais
votre mot de passe.

## Confidentialité

L'e-mail et le mot de passe MyIndygo sont stockés uniquement dans Home Assistant et envoyés uniquement au
cloud MyIndygo, exactement comme le fait l'application mobile. Pour se connecter, l'intégration utilise
l'identifiant client de l'application MyIndygo, le même pour tous les utilisateurs.

## Licence

[MIT](LICENSE)
