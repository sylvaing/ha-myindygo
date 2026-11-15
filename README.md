# MyIndygo (Solem) for Home Assistant

> **Unofficial project.** Not affiliated with, endorsed by or supported by Solem.
> "MyIndygo" and "Solem" are trademarks of their respective owners.

🇫🇷 [Version française](README.fr.md)

Home Assistant custom integration for **Solem MyIndygo** pool equipment, using the same cloud API as the
MyIndygo mobile app.

## Status

🚧 **In development — not usable yet.** Progress is tracked in the
[issues](https://github.com/sylvaing/ha-myindygo/issues) and
[milestones](https://github.com/sylvaing/ha-myindygo/milestones).

The first release (v0.1.0) will be **read-only**: it exposes sensors, it does not control your equipment.

## Supported equipment

Developed and tested with:

| Device | Role |
|---|---|
| LR-MB-10 | LoRa gateway (Wi-Fi) |
| LR-PC | pool controller: filtration pump + 2 auxiliary outputs, water temperature |
| IPX (PoolTech) | interface to a salt electrolyser with pH regulation |

Other MyIndygo devices may work but are untested.

## Planned entities (v0.1.0)

- **Pool controller**: water temperature, filtration running, remaining time, mode, active temperature
  band, auxiliary outputs state.
- **Electrolyser**: pH, salt, production setpoint, pH setpoint, modes, boost, alarms, cell voltage and hours.
- **Gateway**: connectivity, firmware.

## Installation

Not available yet. Once v0.1.0 is released it will be installable through
[HACS](https://hacs.xyz) as a custom repository.

## Privacy

Your MyIndygo e-mail and password are stored in Home Assistant only and sent only to the MyIndygo
cloud (`myindygo.com`), exactly like the mobile app does.

## License

[MIT](LICENSE)
