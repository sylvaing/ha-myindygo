# MyIndygo (Solem) for Home Assistant

> **Unofficial project.** Not affiliated with, endorsed by or supported by Solem.
> "MyIndygo" and "Solem" are trademarks of their respective owners.

🇫🇷 [Version française](README.fr.md)

Home Assistant custom integration for **Solem MyIndygo** pool equipment, using the same cloud API as the
MyIndygo mobile app.

Version 0.1.0 is read-only. The next version adds the manual commands of the pool controller outputs
(forced run, boost, pause, stop, see [Actions](#actions)); programs and electrolyser setpoints are on
the [roadmap](https://github.com/sylvaing/ha-myindygo/milestones).

## Requirements

- Home Assistant 2026.11 or later
- A MyIndygo account (e-mail and password of the mobile app) with equipment reachable through a
  MyIndygo gateway

## Supported equipment

Developed and tested with:

| Device | Role |
|---|---|
| LR-MB-10 | LoRa gateway (Wi-Fi) |
| LR-PC | pool controller: filtration pump, 2 auxiliary outputs, water temperature |
| IPX (PoolTech) | interface to a salt electrolyser with pH regulation |

Other MyIndygo devices may partly work but are untested. Reports and diagnostics are welcome.

## Installation

### With HACS (recommended)

1. In HACS, open the menu ⋮ → **Custom repositories**.
2. Add `https://github.com/sylvaing/ha-myindygo` with the type **Integration**.
3. Search for **MyIndygo (Solem)**, download it, then restart Home Assistant.

### Manually

Copy `custom_components/myindygo` into the `custom_components` folder of your Home Assistant
configuration, then restart Home Assistant.

## Configuration

**Settings → Devices & services → Add integration → MyIndygo (Solem)**, then enter the e-mail and
password of your MyIndygo app account. One device is created per module: gateway → pool controller →
electrolyser.

Options (**Configure** on the integration):

| Option | Default | Range |
|---|---|---|
| Controller status interval | 2 min | 1–30 min |
| Cloud data interval | 15 min | 10–60 min |
| App client identifier (advanced) | built in | leave empty unless the app identifier changes |

Please keep the intervals conservative: the MyIndygo cloud is not designed for frequent polling.

## Entities

### Pool controller (LR-PC)

| Entity | Notes |
|---|---|
| Water temperature | °C |
| Filtration, Output 1, Output 2 | running |
| Filtration / output state | off, program, manual run, boost, frost protection, paused |
| Filtration / output remaining time | minutes |
| Filtration / output mode | off, on, auto |
| Temperature band | band used by the thermo-adaptive schedule, e.g. `18-20 °C` |
| Filtration planned today | hours, decoded from the controller's schedule |
| Diagnostics | last communication, radio command pending, input alert, output rule and type, controller temperature (disabled by default) |

### Electrolyser (IPX PoolTech)

| Entity | Notes |
|---|---|
| pH, pH setpoint, pH regulation | |
| Redox | only when a redox probe is installed |
| Salt | g/L |
| Production setpoint, electrolysis mode | %, off / percentage / auto |
| Boost, boost remaining time | |
| Production, pH injection, wintering | |
| Alarm | the alarm texts are in the `alarms` attribute |
| Diagnostics | electrolysis hours, cell voltage, last report; flow, cover, pH can and external command inputs (disabled by default) |

The electrolyser only reports while the filtration runs, about every 10–15 minutes: check
**Last report** to know how old its values are.

### Gateway (LR-MB-10)

Cloud connection; diagnostics: Wi-Fi link, last restart, reset code (disabled by default).

## Actions

The outputs of the pool controller accept the same manual commands as the MyIndygo app. Each action
targets the running binary sensor of an output (**Filtration**, **Output 1**, **Output 2**), or the
controller device to reach all its outputs:

| Action | Parameter | Effect |
|---|---|---|
| `myindygo.start_manual_run` | duration (1 min – 24 h) | runs the output, then returns it to its program |
| `myindygo.start_boost` | duration (1 min – 24 h) | boost of the filtration or treatment output |
| `myindygo.pause` | days (1 – 30) | stops the output, its program included |
| `myindygo.stop_manual_command` | — | ends the forced run, boost or pause |

```yaml
action: myindygo.start_manual_run
target:
  entity_id: binary_sensor.lrpc_xxxxxx_filtration
data:
  duration: "01:30:00"
```

Good to know:

- The controller **silently ignores** a manual command on an output whose mode is not **Auto** (check
  the *mode* sensor). The integration refuses the action with an error instead of pretending it
  worked; change the mode in the MyIndygo app first. Boost is only offered for the filtration and
  treatment outputs, like in the app.
- The cloud answers before the radio exchange with the controller (**Radio command pending** is on
  meanwhile). The integration reads the status again 10 seconds later and logs a warning if the
  command had no visible effect.
- An auxiliary output configured to force the filtration is commanded alone (the app also extends
  the filtration in that case); variable speed pumps are not supported.

## How it works

The integration polls the MyIndygo cloud (`myindygo.com`) like the mobile app:

- every 2 minutes, the real-time status of the pool controller, read through the gateway;
- every 15 minutes, the modules (including electrolyser data), pool measures and programs.

A short gateway outage keeps the last controller status for up to about 6 minutes.

## Troubleshooting

Download the diagnostics from the integration page (⋮ → **Download diagnostics**) and attach them to
an [issue](https://github.com/sylvaing/ha-myindygo/issues). Personal data (e-mail, address, location,
serial numbers, MAC addresses, tokens) is removed from that file. Never post your password.

## Privacy

Your MyIndygo e-mail and password are stored in Home Assistant only and sent only to the MyIndygo
cloud, exactly like the mobile app does. To log in, the integration uses the client identifier of the
MyIndygo app, which is the same for every user.

## License

[MIT](LICENSE)
