# Changelog

## Unreleased

### Added
- Integration icon (original artwork, a generic pool symbol) shipped in the integration's `brand/`
  folder, shown by Home Assistant (2026.3 and later) and HACS.
- Manual commands of the pool controller outputs, as entity actions on the output binary sensors
  (or the controller device): `myindygo.start_manual_run` (duration), `myindygo.start_boost`
  (duration, filtration and treatment outputs), `myindygo.pause` (days) and
  `myindygo.stop_manual_command` (#15).
- Commands on an output that is not in mode Auto are refused with an explanation, since the
  controller silently ignores them; the status is read again 10 s after a command and a warning is
  logged if it had no visible effect.

## 0.1.0 — 2026-11-21

First release. **Read-only**: the integration shows your equipment, it does not control it yet.

### Added
- Set-up from the UI with the e-mail and password of the MyIndygo app account; reauthentication
  when the password changes.
- Options: controller status interval (1–30 min, default 2), cloud data interval (10–60 min,
  default 15), and an advanced override of the app client identifier.
- One device per module, linked gateway → pool controller → electrolyser.
- Pool controller (LR-PC): water temperature; filtration and auxiliary outputs running, state
  (program, manual run, boost, frost protection, paused), remaining time, mode; active temperature
  band and filtration planned today; diagnostics.
- Electrolyser (IPX PoolTech): pH, pH setpoint and regulation mode, salt, production setpoint,
  electrolysis mode, boost, production, pH injection, wintering, alarm with the alarm texts;
  diagnostics (electrolysis hours, cell voltage, last report, hardware inputs).
- Gateway (LR-MB-10): cloud connection, Wi-Fi link, last restart.
- Short gateway outages (up to ~6 min) keep the last controller status instead of making every
  live entity unavailable.
- Diagnostics download with personal data redacted.

### Known limitations
- Cloud only (`myindygo.com`); the gateway's local API is not used yet.
- The electrolyser only reports while the filtration runs, about every 10–15 minutes.
- Validated on one installation (LR-MB-10 + LR-PC + IPX PoolTech electrolyser).
