# Changelog

## 1.1.3 - 2026-10-11

- Vacuum state while the station washes the mops (MIoT status 7) is now
  `cleaning` instead of `returning`, and the trip back to wash them in the
  middle of a task (status 20) is `returning` instead of `paused`. The meaning
  was confirmed in the state history of two robots. The vacuum entity and the
  location sensor now use one status table.
- Automations that treat `docked` as the end of a task keep working: washing
  the mops during a task never reports `docked`.
- The start check no longer gives up at once when the robot was already
  paused with a fault before the call; it waits the full window instead.
- README: the robot always begins in the room with its station.
- Tests on the Home Assistant test framework (Python 3.14) run in CI.

## 1.1.2 - 2026-10-11

- Room cleaning start confirmation waits up to 5 minutes instead of 30
  seconds. With mopping the robot first washes its mops in the station for
  about 3 minutes, and the previous task often stays in the active task
  property after it finished, so a repeated start with the same rooms was
  reported as failed although the robot started.
- A refusal (for example `210030`, low clean water) is still reported at once:
  the check stops as soon as the robot pauses with a fault code.

## 1.1.1 - 2026-10-11

- The integration is now shown as "X20 Max (Smart Service)". The domain
  `xiaomi_x20_max`, entities, services and settings do not change.
- The README states that the integration is not affiliated with Xiaomi and is
  distributed under the Xiaomi Home license for personal, non-commercial use.
- Removed the donation link.

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
