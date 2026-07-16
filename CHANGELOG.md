# Changelog

## 1.0.1 - 2026-07-16

- Added a readable message for fault code `210030`: low clean-water tank level.
- Room sensor now exposes readable room names as its state, with IDs/names in
  attributes.
- Added a current-location sensor with conservative room detection and diagnostic
  attributes for map position and active cleaning queue.

## 1.0.0

- Initial public release for `xiaomi.vacuum.d109gl`.
- Bundled light/dark-theme-compatible integration brand icon.
- Independent Xiaomi Cloud polling after one-time OAuth bootstrap.
- Vacuum, sensor, select, switch, number and button entities.
- Room cleaning by ID or exact name.
- Omni station and advanced MIoT services.
- English and Polish translations.
- Optional maintenance-notification blueprint.
