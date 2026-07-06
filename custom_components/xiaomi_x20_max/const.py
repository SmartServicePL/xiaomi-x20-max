"""Constants and the X20 Max MIoT model definition."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.const import Platform

DOMAIN = "xiaomi_x20_max"
MODEL = "xiaomi.vacuum.d109gl"
CONF_SOURCE_ENTITY_ID = "source_entity_id"
CONF_DID = "did"
CONF_NAME = "name"
CONF_FIRMWARE = "firmware"
CLOUD_DATA_KEY = "_cloud"

PLATFORMS = (
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
)


@dataclass(frozen=True, slots=True)
class PropertyRef:
    """Reference to a MIoT property."""

    siid: int
    piid: int


@dataclass(frozen=True, slots=True)
class ActionRef:
    """Reference to a MIoT action."""

    siid: int
    aiid: int


@dataclass(frozen=True, slots=True)
class EnumProperty:
    """Writable enumerated MIoT property."""

    key: str
    ref: PropertyRef
    options: dict[str, int]
    source_states: dict[str, str]
    icon: str


@dataclass(frozen=True, slots=True)
class BoolProperty:
    """Writable boolean MIoT property."""

    key: str
    ref: PropertyRef
    icon: str
    advanced: bool = False


@dataclass(frozen=True, slots=True)
class ButtonAction:
    """Parameterless MIoT action represented as a button."""

    key: str
    ref: ActionRef
    icon: str
    advanced: bool = False


def _enum(
    key: str,
    siid: int,
    piid: int,
    values: tuple[tuple[str, int, str], ...],
    icon: str,
) -> EnumProperty:
    return EnumProperty(
        key=key,
        ref=PropertyRef(siid, piid),
        options={item[0]: item[1] for item in values},
        source_states={item[0]: item[2] for item in values},
        icon=icon,
    )


ENUM_PROPERTIES: tuple[EnumProperty, ...] = (
    _enum(
        "cleaning_mode",
        2,
        4,
        (
            ("vacuum", 1, "Sweep"),
            ("mop", 2, "Mop"),
            ("vacuum_and_mop", 3, "Sweep Mop"),
            ("vacuum_then_mop", 4, "Sweep Before Mopping"),
        ),
        "mdi:robot-vacuum",
    ),
    _enum(
        "cleaning_passes",
        2,
        8,
        (
            ("one", 1, "One Time"),
            ("two", 2, "Two Time"),
            ("three", 3, "Three Time"),
        ),
        "mdi:repeat",
    ),
    _enum(
        "suction_power",
        2,
        9,
        (
            ("silent", 1, "Silent"),
            ("standard", 2, "Basic"),
            ("strong", 3, "Strong"),
            ("turbo", 4, "Full Speed"),
        ),
        "mdi:fan",
    ),
    _enum(
        "mop_water_level",
        2,
        10,
        (
            ("off", 0, "Off"),
            ("low", 1, "Level1"),
            ("medium", 2, "Level2"),
            ("high", 3, "Level3"),
        ),
        "mdi:water-percent",
    ),
    _enum(
        "mop_wash_frequency",
        2,
        29,
        (
            ("by_room", 0, "By Room"),
            ("by_area", 1, "By Area"),
            ("by_time", 2, "By Time"),
        ),
        "mdi:washing-machine",
    ),
    _enum(
        "mop_wash_intensity",
        2,
        30,
        (
            ("deep", 0, "Deep"),
            ("daily", 1, "Daily"),
            ("water_saving", 2, "Save Water"),
        ),
        "mdi:water-sync",
    ),
    _enum(
        "drying_time",
        2,
        31,
        (
            ("two_hours", 1, "2 Hours"),
            ("three_hours", 2, "3 Hours"),
            ("four_hours", 3, "4 Hours"),
        ),
        "mdi:timer-outline",
    ),
    _enum(
        "dust_collection_frequency",
        2,
        33,
        (
            ("once", 1, "Once"),
            ("twice", 2, "Twice"),
            ("three_times", 3, "Triple"),
        ),
        "mdi:delete-sweep",
    ),
    _enum(
        "mop_water_no_tank",
        2,
        60,
        (("daily", 0, "Daily"), ("deep", 1, "Deep")),
        "mdi:water",
    ),
    _enum(
        "mop_wash_area",
        2,
        61,
        (
            ("five_m2", 0, "Five Square  Meters"),
            ("ten_m2", 1, "Ten Square  Meters"),
            ("eight_m2", 2, "Eight Square  Meters"),
            ("fifteen_m2", 3, "Fifteen Square  Meters"),
            ("twenty_m2", 4, "Twenty Square  Meters"),
            ("twenty_five_m2", 5, "Twenty Five Square  Meters"),
        ),
        "mdi:floor-plan",
    ),
    _enum(
        "carpet_cleaning",
        2,
        73,
        (
            ("adaptive", 0, "Self Adaption"),
            ("avoid", 1, "Avoid"),
            ("ignore", 2, "Ignore"),
            ("cross", 3, "Span"),
        ),
        "mdi:rug",
    ),
    _enum(
        "cleaning_route",
        2,
        74,
        (
            ("quick", 1, "Quick"),
            ("daily", 2, "Daily"),
            ("careful", 3, "Careful"),
        ),
        "mdi:map-marker-path",
    ),
    _enum(
        "obstacle_avoidance",
        2,
        75,
        (
            ("fewer_collisions", 0, "Less Collisions"),
            ("high_coverage", 1, "High Coverage"),
        ),
        "mdi:car-brake-alert",
    ),
    _enum(
        "edge_mop_frequency",
        2,
        80,
        (
            ("every_time", 1, "Every Time"),
            ("every_seven_runs", 2, "7 Sweeps"),
        ),
        "mdi:wall",
    ),
    _enum(
        "dust_collection_power",
        2,
        82,
        (
            ("silent", 0, "Silent"),
            ("normal", 1, "Normal"),
            ("strong", 2, "Strong"),
        ),
        "mdi:fan-chevron-up",
    ),
    _enum(
        "worry_free_mode",
        2,
        83,
        (
            ("silent", 0, "Silent"),
            ("deep", 1, "Deep Clean"),
            ("standard", 2, "Standard"),
        ),
        "mdi:auto-fix",
    ),
    _enum(
        "mop_wash_temperature",
        2,
        84,
        (
            ("ambient", 0, "Ordinary Temperature"),
            ("warm", 1, "Warm"),
            ("hot", 2, "Hot"),
            ("smart", 3, "Smart"),
        ),
        "mdi:coolant-temperature",
    ),
    _enum(
        "map_switching",
        10,
        10,
        (("manual", 0, "Manual"), ("automatic", 1, "Auto")),
        "mdi:map-sync",
    ),
    _enum(
        "detergent_amount",
        18,
        3,
        (
            ("low", 0, "Few"),
            ("standard", 1, "Standard"),
            ("high", 2, "Many"),
            ("very_high", 3, "Lots Of"),
        ),
        "mdi:bottle-tonic-plus",
    ),
)


BOOL_PROPERTIES: tuple[BoolProperty, ...] = (
    BoolProperty("carpet_boost", PropertyRef(2, 20), "mdi:rug"),
    BoolProperty("carpet_avoidance", PropertyRef(2, 21), "mdi:rug-outline"),
    BoolProperty("show_carpets", PropertyRef(2, 22), "mdi:map-marker"),
    BoolProperty("resume_cleaning", PropertyRef(2, 23), "mdi:backup-restore"),
    BoolProperty("automatic_mop_wash", PropertyRef(2, 28), "mdi:washing-machine"),
    BoolProperty("automatic_dust_collection", PropertyRef(2, 32), "mdi:delete-sweep"),
    BoolProperty("automatic_mop_drying", PropertyRef(2, 34), "mdi:weather-windy"),
    BoolProperty("automatic_water_change", PropertyRef(2, 35), "mdi:water-sync", True),
    BoolProperty("use_detergent", PropertyRef(2, 36), "mdi:bottle-tonic-plus"),
    BoolProperty("remote_exit_dialog", PropertyRef(2, 38), "mdi:remote", True),
    BoolProperty("detergent_auto_dosing", PropertyRef(2, 59), "mdi:eyedropper"),
    BoolProperty(
        "detergent_low_reminder", PropertyRef(2, 71), "mdi:bottle-tonic-alert"
    ),
    BoolProperty("carpet_deep_cleaning", PropertyRef(2, 76), "mdi:rug"),
    BoolProperty("carpet_detection", PropertyRef(2, 77), "mdi:radar"),
    BoolProperty("carpets_first", PropertyRef(2, 78), "mdi:order-bool-ascending"),
    BoolProperty("edge_mopping", PropertyRef(2, 79), "mdi:wall"),
    BoolProperty("alarm", PropertyRef(4, 1), "mdi:volume-high"),
    BoolProperty("child_lock", PropertyRef(5, 1), "mdi:lock"),
    BoolProperty("stop_map_upload", PropertyRef(10, 11), "mdi:cloud-off-outline", True),
    BoolProperty("do_not_disturb", PropertyRef(11, 1), "mdi:minus-circle"),
    BoolProperty(
        "detergent_station_dosing", PropertyRef(18, 2), "mdi:eyedropper", True
    ),
    BoolProperty("sewage_self_cleaning", PropertyRef(20, 7), "mdi:pipe-valve", True),
)


BUTTON_ACTIONS: tuple[ButtonAction, ...] = (
    ButtonAction("start_vacuuming", ActionRef(2, 4), "mdi:vacuum"),
    ButtonAction("start_mopping", ActionRef(2, 5), "mdi:water"),
    ButtonAction("start_vacuum_and_mop", ActionRef(2, 6), "mdi:robot-vacuum"),
    ButtonAction("resume", ActionRef(2, 8), "mdi:play"),
    ButtonAction("start_mapping", ActionRef(2, 17), "mdi:map-plus", True),
    ButtonAction("empty_dust_bin", ActionRef(2, 18), "mdi:delete-sweep"),
    ButtonAction("wash_mops", ActionRef(2, 19), "mdi:washing-machine"),
    ButtonAction("dry_mops", ActionRef(2, 20), "mdi:weather-windy"),
    ButtonAction("leave_station", ActionRef(2, 21), "mdi:garage-open", True),
    ButtonAction("stop_mop_wash", ActionRef(2, 31), "mdi:washing-machine-off"),
    ButtonAction("stop_mop_drying", ActionRef(2, 32), "mdi:fan-off"),
    ButtonAction("resume_mapping", ActionRef(2, 33), "mdi:map-check", True),
    ButtonAction("finish_mapping", ActionRef(2, 34), "mdi:map-marker-check", True),
    ButtonAction("pause_mapping", ActionRef(2, 35), "mdi:map-clock", True),
    ButtonAction("return_to_wash_mops", ActionRef(2, 36), "mdi:home-import-outline"),
    ButtonAction("start_water_check", ActionRef(2, 45), "mdi:water-check", True),
    ButtonAction("cancel_water_check", ActionRef(2, 46), "mdi:water-remove", True),
    ButtonAction("start_charging", ActionRef(3, 1), "mdi:battery-charging"),
    ButtonAction("identify", ActionRef(6, 1), "mdi:map-marker-radius"),
    ButtonAction("reset_mop", ActionRef(9, 1), "mdi:restart", True),
    ButtonAction("clear_map", ActionRef(10, 1), "mdi:map-remove", True),
    ButtonAction("save_map", ActionRef(10, 4), "mdi:content-save", True),
    ButtonAction("automatic_room_partition", ActionRef(10, 5), "mdi:floor-plan", True),
    ButtonAction("refresh_map_properties", ActionRef(10, 7), "mdi:map-sync", True),
    ButtonAction("reset_main_brush", ActionRef(12, 1), "mdi:restart", True),
    ButtonAction("reset_side_brush", ActionRef(13, 1), "mdi:restart", True),
    ButtonAction("reset_filter", ActionRef(14, 1), "mdi:restart", True),
    ButtonAction("reset_detergent", ActionRef(18, 1), "mdi:restart", True),
    ButtonAction("reset_dust_bag", ActionRef(19, 1), "mdi:restart", True),
)

STATION_ACTIONS: dict[str, ActionRef] = {
    "empty": ActionRef(2, 18),
    "wash_mops": ActionRef(2, 19),
    "dry_mops": ActionRef(2, 20),
    "leave_station": ActionRef(2, 21),
    "stop_washing": ActionRef(2, 31),
    "stop_drying": ActionRef(2, 32),
    "return_to_wash": ActionRef(2, 36),
}

CLEANING_MODES: dict[str, int] = {
    "vacuum": 1,
    "mop": 2,
    "vacuum_and_mop": 3,
    "vacuum_then_mop": 4,
}

SUCTION_LEVELS: dict[str, int] = {
    "silent": 1,
    "standard": 2,
    "strong": 3,
    "turbo": 4,
}

WATER_LEVELS: dict[str, int] = {
    "off": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}

ROUTE_LEVELS: dict[str, int] = {"quick": 1, "daily": 2, "careful": 3}

# Every readable property used by the dedicated X20 Max entities.  The raw
# services remain available for model properties and actions not represented
# by a friendly entity.
POLL_PROPERTIES: tuple[PropertyRef, ...] = tuple(
    PropertyRef(siid, piid)
    for siid, piid in (
        (2, 2),
        (2, 3),
        (2, 4),
        (2, 6),
        (2, 7),
        (2, 8),
        (2, 9),
        (2, 10),
        (2, 16),
        (2, 17),
        (2, 18),
        (2, 20),
        (2, 21),
        (2, 22),
        (2, 23),
        (2, 28),
        (2, 29),
        (2, 30),
        (2, 31),
        (2, 32),
        (2, 33),
        (2, 34),
        (2, 35),
        (2, 36),
        (2, 38),
        (2, 40),
        (2, 53),
        (2, 54),
        (2, 59),
        (2, 60),
        (2, 61),
        (2, 62),
        (2, 66),
        (2, 67),
        (2, 70),
        (2, 71),
        (2, 72),
        (2, 73),
        (2, 74),
        (2, 75),
        (2, 76),
        (2, 77),
        (2, 78),
        (2, 79),
        (2, 80),
        (2, 81),
        (2, 82),
        (2, 83),
        (2, 84),
        (3, 1),
        (3, 2),
        (4, 1),
        (4, 2),
        (5, 1),
        (9, 1),
        (9, 2),
        (10, 3),
        (10, 10),
        (10, 11),
        (10, 12),
        (10, 14),
        (11, 1),
        (11, 2),
        (12, 1),
        (12, 2),
        (13, 1),
        (13, 2),
        (14, 1),
        (14, 2),
        (18, 1),
        (18, 2),
        (18, 3),
        (19, 1),
        (19, 2),
        (20, 7),
        (20, 3),
        (20, 8),
    )
)

MODEL_ACTIONS: frozenset[ActionRef] = frozenset(
    {
        *(item.ref for item in BUTTON_ACTIONS),
        *STATION_ACTIONS.values(),
        ActionRef(2, 1),
        ActionRef(2, 2),
        ActionRef(2, 3),
        ActionRef(2, 7),
        ActionRef(2, 16),
    }
)
