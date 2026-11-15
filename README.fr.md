# MyIndygo (Solem) pour Home Assistant

> **Projet non officiel.** Ni affilié à Solem, ni approuvé ou supporté par Solem.
> « MyIndygo » et « Solem » sont des marques de leurs propriétaires respectifs.

🇬🇧 [English version](README.md)

Intégration personnalisée Home Assistant pour les équipements de piscine **Solem MyIndygo**, qui utilise la
même API cloud que l'application mobile MyIndygo.

## État

🚧 **En développement — pas encore utilisable.** L'avancement est suivi dans les
[issues](https://github.com/sylvaing/ha-myindygo/issues) et les
[jalons](https://github.com/sylvaing/ha-myindygo/milestones).

La première version (v0.1.0) sera en **lecture seule** : elle expose des capteurs, elle ne pilote pas vos
équipements.

## Équipements pris en charge

Développé et testé avec :

| Appareil | Rôle |
|---|---|
| LR-MB-10 | passerelle LoRa (Wi-Fi) |
| LR-PC | coffret piscine : pompe de filtration + 2 sorties auxiliaires, température de l'eau |
| IPX (PoolTech) | interface vers un électrolyseur au sel avec régulation pH |

D'autres équipements MyIndygo peuvent fonctionner mais ne sont pas testés.

## Entités prévues (v0.1.0)

- **Coffret** : température de l'eau, filtration en marche, temps restant, mode, tranche de température
  active, état des sorties auxiliaires.
- **Électrolyseur** : pH, sel, consigne de production, consigne pH, modes, boost, alarmes, tension et heures
  de cellule.
- **Passerelle** : connexion, firmware.

## Installation

Pas encore disponible. Une fois la v0.1.0 publiée, elle s'installera via [HACS](https://hacs.xyz) en dépôt
personnalisé.

## Confidentialité

L'e-mail et le mot de passe MyIndygo sont stockés uniquement dans Home Assistant et envoyés uniquement au
cloud MyIndygo (`myindygo.com`), exactement comme le fait l'application mobile.

## Licence

[MIT](LICENSE)
