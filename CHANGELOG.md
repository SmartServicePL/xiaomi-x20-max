# Changelog

## 1.1.0

- Room cleaning start is now verified. The robot answers the room-cleaning
  action with the generic MIoT code `-704083036` both when it starts and when
  it refuses (no clean water, station fault, robot busy). After that code the
  integration reads the robot status and active task for up to 30 seconds and
  `clean_rooms` / `vacuum.clean_area` fail with a readable error when the
  robot did not start. The raw `execute_action` service now reports this code
  as an error.
- Room IDs are always checked against the robot's active map. When the room
  list is missing it is read again; if it is still missing the start is
  rejected instead of sending unchecked IDs.
- `vacuum.clean_area`: a repair issue is raised when the robot's rooms no
  longer match the saved area mapping, and the mapping dialog shows an error
  instead of an empty list while the map is not loaded.
- Re-authentication: when Xiaomi rejects the OAuth grant, the integration
  first imports a newer grant from Xiaomi Home and otherwise asks to
  re-authenticate (sign in again in Xiaomi Home, then confirm).
- Network errors no longer include aiohttp exception texts, which could
  contain the refresh token; timeouts have a readable message.
- Polling runs as a background task with backoff (30 s up to 5 min) after
  errors and logs only the change between failing and working. The robot is
  shown as unavailable when Xiaomi reports it offline.
- Diagnostics redact the cloud device ID and room names again.
- Full English translation; service errors are translated.
- Clear map, automatic room partition and start mapping buttons are disabled
  by default for new installations (existing entities are not changed).
- Large, frequently changing attributes are excluded from the recorder.
- Maintenance blueprint: no burst of notifications after a cloud outage,
  restart or reload; optional Polish notifications; `min_version` 2024.10.0.

## 1.0.1 - 2026-07-16

- Added a readable message for fault code `210030`: low clean-water tank level.
- Room sensor now exposes readable room names as its state, with IDs/names in
  attributes.
- Added a current-location sensor with conservative room detection and diagnostic
  attributes for map position and active cleaning queue.

## 1.0.0 - 2026-07-06

- Initial public release for `xiaomi.vacuum.d109gl`.
- Bundled light/dark-theme-compatible integration brand icon.
- Independent Xiaomi Cloud polling after one-time OAuth bootstrap.
- Vacuum, sensor, select, switch, number and button entities.
- Room cleaning by ID or exact name.
- Omni station and advanced MIoT services.
- English and Polish translations.
- Optional maintenance-notification blueprint.
