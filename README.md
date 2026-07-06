# Xiaomi Robot Vacuum X20 Max for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)
[![Validate](https://github.com/SmartServicePL/xiaomi-x20-max/actions/workflows/validate.yml/badge.svg)](https://github.com/SmartServicePL/xiaomi-x20-max/actions/workflows/validate.yml)

Unofficial, model-specific Home Assistant integration for
`xiaomi.vacuum.d109gl` (Xiaomi Robot Vacuum X20 Max).

[Polska instrukcja](README_PL.md)

## Features

- Native vacuum entity: start, pause, stop, locate and return to base.
- Exact room IDs and names from the active map.
- Clean one or multiple rooms by ID or exact name.
- Vacuum/mop mode, suction, water level, 1–3 passes and route selection.
- Omni station actions: empty bin, wash mops and dry mops.
- Battery, cleaning history, faults and consumable-life sensors.
- Controls for carpet handling, obstacle avoidance, DND and detergent.
- Buttons for mapping and resetting consumable counters.
- Advanced raw MIoT property and action services.
- English and Polish translations.

## Requirements

- Home Assistant 2026.7.0 or newer.
- Xiaomi Robot Vacuum X20 Max with model ID `xiaomi.vacuum.d109gl`.
- The robot configured in the Xiaomi Home mobile app.
- The official **Xiaomi Home** integration configured in Home Assistant with
  the same Xiaomi account and region. It supplies the initial OAuth grant.
- Internet access from Home Assistant to `*.ha.api.io.mi.com`.

## Installation with HACS

1. In HACS, open **Integrations**.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/SmartServicePL/xiaomi-x20-max` as an
   **Integration** repository.
4. Install **Xiaomi Robot Vacuum X20 Max**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & services → Add integration**.
7. Search for **Xiaomi Robot Vacuum X20 Max** and select the robot.

If setup reports that OAuth credentials are unavailable, configure or reload
the official Xiaomi Home integration first and retry.

## Manual installation

Copy `custom_components/xiaomi_x20_max` into the `custom_components`
directory in your Home Assistant configuration, restart Home Assistant and
add the integration from the UI.

## Clean rooms

Room IDs and names are available in the **Rooms and IDs** sensor and in the
vacuum entity attributes.

```yaml
action: xiaomi_x20_max.clean_rooms
data:
  entity_id: vacuum.my_x20_max_control
  rooms:
    - Kitchen
    - 10
  mode: vacuum_and_mop
  suction: turbo
  water_level: medium
  passes: 2
  route: careful
```

`rooms` accepts IDs, exact room names, or a mixture of both.

## Station actions

```yaml
action: xiaomi_x20_max.station_action
data:
  entity_id: vacuum.my_x20_max_control
  action: wash_mops
```

Available actions: `empty`, `wash_mops`, `dry_mops`, `leave_station`,
`stop_washing`, `stop_drying` and `return_to_wash`.

## Maintenance notification blueprint

The optional blueprint creates reusable alerts for station faults, detergent,
mops, filter, brushes and dust bag. Import it once for each robot and select
your own mobile notification action:

[Import maintenance blueprint](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FSmartServicePL%2Fxiaomi-x20-max%2Fblob%2Fmain%2Fblueprints%2Fautomation%2FSmartServicePL%2Fx20_max_maintenance.yaml)

## Authentication and privacy

On first setup the integration imports an existing Xiaomi OAuth grant from
the official Xiaomi Home integration into its own Home Assistant storage.
After that it refreshes the OAuth token independently. Xiaomi account
passwords and local device tokens are not stored by this integration.

Credentials remain inside Home Assistant and are only sent to Xiaomi Cloud.
Diagnostics redact the cloud device ID and room names.

## Limitations

- Cloud polling; this is not a local integration.
- One Xiaomi OAuth account/region per Home Assistant installation.
- No map rendering.
- The device does not expose continuous clean/dirty-water percentages.
- Some MIoT properties are undocumented and can change with firmware.

The raw `set_property` and `execute_action` services are intended for advanced
users. Incorrect values may change maps or device settings.

## Support

Open an [issue](https://github.com/SmartServicePL/xiaomi-x20-max/issues) and
attach Home Assistant diagnostics. Never attach `.storage` files or tokens.

## License and disclaimer

MIT licensed. This project is not affiliated with Xiaomi. Xiaomi Cloud API use
is intended only for personal, non-commercial Home Assistant installations;
see [LICENSE_XIAOMI.md](LICENSE_XIAOMI.md).
