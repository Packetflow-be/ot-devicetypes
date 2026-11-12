"""Turn a parsed GSDML file into NetBox device type and module type definitions.

The output follows the format of the NetBox community device type library
(https://github.com/netbox-community/devicetype-library).

A GSDML file knows the PROFINET side of a device and nothing else, so each
definition is a skeleton: model, part number, Ethernet ports, slots. Whatever
the file cannot know (power input, USB or serial ports, weight) comes from a
hand-kept source configuration, see docs/sources.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .gsdml import AccessPoint, GsdFile, Module, Port

SIEMENS_VENDOR_ID = 0x002A

# PROFINET vendor ID -> manufacturer name as NetBox users write it. GSDML files
# spell the vendor in many ways ("SIEMENS", "Siemens AG"); a source
# configuration can override this with `manufacturer:`.
MANUFACTURERS: dict[int, str] = {
    0x002A: "Siemens",
    0x010C: "HMS Networks",
    0x011D: "WAGO",
    0x012F: "Murrelektronik",
    0x0136: "ifm",
    0x013D: "Turck",
    0x014D: "Festo",
    0x01C6: "Advantech",
}

# IANA MAU type -> (NetBox interface type, speed rank, note)
MAU_TYPES: dict[int, tuple[str, int, str]] = {
    10: ("other", 10, "10BASE-T"),
    11: ("other", 10, "10BASE-T"),
    15: ("100base-tx", 100, ""),
    16: ("100base-tx", 100, ""),
    17: ("100base-fx", 100, ""),
    18: ("100base-fx", 100, ""),
    23: ("1000base-lx", 1000, ""),
    24: ("1000base-lx", 1000, ""),
    25: ("1000base-sx", 1000, ""),
    26: ("1000base-sx", 1000, ""),
    29: ("1000base-t", 1000, ""),
    30: ("1000base-t", 1000, ""),
    54: ("100base-fx", 100, "POF/PCF fibre (100BASE-PX)"),
}

DEVICE_KEY_ORDER = [
    "manufacturer",
    "model",
    "slug",
    "part_number",
    "description",
    "u_height",
    "is_full_depth",
    "subdevice_role",
    "is_powered",
    "airflow",
    "weight",
    "weight_unit",
    "console-ports",
    "console-server-ports",
    "power-ports",
    "power-outlets",
    "interfaces",
    "front-ports",
    "rear-ports",
    "module-bays",
    "device-bays",
    "inventory-items",
    "comments",
]
MODULE_KEY_ORDER = [key for key in DEVICE_KEY_ORDER if key not in ("slug", "u_height", "is_full_depth")]

DEFAULT_PORT_NAME = "X{interface} P{port}"
DEFAULT_MAX_MODULE_BAYS = 64


@dataclass
class Skipped:
    order_number: str
    name: str
    reason: str


@dataclass
class Result:
    device_types: list[dict] = field(default_factory=list)
    module_types: list[dict] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def slugify(value: str) -> str:
    """The slug rule of the community library's tests (tests/device_types.py)."""
    slug = value.casefold()
    for old, new in (
        (" ", "-"),
        ("sfp+", "sfpp"),
        ("poe+", "poep"),
        ("-+", "-plus"),
        ("+", "-plus-"),
        ("_", "-"),
        ("&", "-and-"),
        ("!", ""),
        ("/", "-"),
        (",", ""),
        ("'", ""),
        ("*", "-"),
        ("(", ""),
        (")", ""),
        (";", ""),
        (".", "-"),
    ):
        slug = slug.replace(old, new)
    return slug.rstrip("-")


def normalise_order_number(order_number: str, vendor_id: int) -> str:
    order_number = " ".join(order_number.split())
    if vendor_id == SIEMENS_VENDOR_ID:
        # Siemens prints article numbers with a space after the fourth character
        # in catalogues ("6ES7 158-3AD01-0XA0") and without it in its web shop.
        order_number = order_number.replace(" ", "")
    return order_number


def is_wildcard(order_number: str) -> bool:
    """True when the order number stands for a product family, not one article."""
    if not order_number or "*" in order_number or "?" in order_number:
        return True
    # '6SL32xx-xYxxx-xxFx', '75x-400': a lower-case x is a placeholder, unless
    # the number has other lower-case letters and so is simply written that way.
    lower = {c for c in order_number if c.islower()}
    return lower == {"x"}


def clean_model(names: list[str], order_number: str) -> str:
    """A model name from the access point names of one article."""
    cleaned = []
    for name in names:
        name = re.sub(r"\s*\((?:FW|HW)[^)]*\)", "", name)  # "(FW 06)"
        name = re.sub(r"\s+V\d[\w.]*$", "", name.strip())  # trailing firmware version
        if len(names) > 1:
            name = re.sub(r"\s+X\d+$", "", name)  # one entry per interface: "Coupler X1", "Coupler X2"
        cleaned.append(name.strip())
    cleaned = [name for name in dict.fromkeys(cleaned) if name]
    if not cleaned:
        return order_number
    if len(cleaned) == 1:
        return cleaned[0]
    # Several names for one article ("Coupler X1", "Coupler X2"): keep what they share.
    prefix = cleaned[0]
    for name in cleaned[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
    prefix = prefix.rstrip(" -,/")
    return prefix if len(prefix) >= 3 else cleaned[-1]


def interface_type(port: Port) -> tuple[str, str]:
    """(NetBox interface type, description) for the fastest medium the port supports."""
    best = ("other", -1, "")
    unknown = []
    for mau in port.mau_types:
        if mau not in MAU_TYPES:
            unknown.append(str(mau))
            continue
        if MAU_TYPES[mau][1] > best[1]:
            best = MAU_TYPES[mau]
    description = best[2]
    if best[1] < 0:
        description = "MAU type " + ", ".join(unknown)
    return best[0], description


def _ordered(definition: dict, order: list[str]) -> dict:
    known = {key: definition[key] for key in order if key in definition}
    known.update({key: value for key, value in definition.items() if key not in known})
    return known


def _matches(patterns: list[str] | None, value: str) -> bool:
    return any(re.search(pattern, value) for pattern in patterns or [])


def _apply_overlay(definition: dict, overlay: dict) -> None:
    if overlay.get("model"):
        definition["model"] = overlay["model"]
    for key, value in (overlay.get("set") or {}).items():
        definition[key] = value
    for key, items in (overlay.get("add") or {}).items():
        definition[key] = list(definition.get(key) or []) + list(items)


def _truncate(text: str, limit: int = 200) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _is_hardware(module: Module | None) -> bool:
    return bool(module and module.order_number and not is_wildcard(module.order_number))


def convert(gsd: GsdFile, config: dict | None = None) -> Result:
    config = config or {}
    result = Result()
    manufacturer = config.get("manufacturer") or MANUFACTURERS.get(gsd.vendor_id) or gsd.vendor_name
    port_name = config.get("port_name") or DEFAULT_PORT_NAME
    bays = config.get("module_bays", "auto")
    max_bays = bays if isinstance(bays, int) else DEFAULT_MAX_MODULE_BAYS
    overlays: dict = config.get("devices") or {}
    expand: dict = {
        normalise_order_number(key, gsd.vendor_id): value for key, value in (config.get("expand") or {}).items()
    }
    source_note = f"Generated from {gsd.path.name} by ot-devicetypes."

    # One physical article shows up once per firmware release, and a device with
    # two PROFINET interfaces once per interface: group on the order number.
    groups: dict[str, list[AccessPoint]] = {}
    for access_point in gsd.access_points:
        order_number = normalise_order_number(access_point.order_number, gsd.vendor_id)
        groups.setdefault(order_number, []).append(access_point)

    used_modules: dict[str, Module] = {}
    family_modules: set[str] = set()
    for order_number, access_points in groups.items():
        names = [ap.name for ap in access_points]
        if not order_number:
            result.skipped.append(Skipped("", names[-1], "no order number"))
            continue
        if _matches(config.get("exclude"), order_number) or (
            config.get("include") and not _matches(config.get("include"), order_number)
        ):
            result.skipped.append(Skipped(order_number, names[-1], "left out by the source configuration"))
            continue
        if is_wildcard(order_number):
            part_numbers = expand.get(order_number)
            if not part_numbers:
                result.skipped.append(
                    Skipped(order_number, names[-1], "order number is a family pattern; list the articles under expand")
                )
                continue
        else:
            part_numbers = [order_number]

        # Newer firmware wins where two access points describe the same port.
        ports: dict[int, Port] = {}
        for access_point in sorted(access_points, key=lambda ap: ap.position):
            for port in access_point.ports:
                ports[port.subslot] = port
        if not ports:
            result.skipped.append(
                Skipped(order_number, names[-1], "no fixed Ethernet port (ports sit on a pluggable adapter)")
            )
            continue

        newest = max(access_points, key=lambda ap: ap.position)
        # A device with two PROFINET interfaces is described once per interface;
        # each text then covers half of the device, so it is no description of the whole.
        per_interface = len({port.interface for port in ports.values()}) > 1
        slots = max((ap.slots for ap in access_points), key=len)
        usable = [gsd.modules.get(module_id) for ap in access_points for module_id in ap.module_ids]
        hardware = [module for module in usable if _is_hardware(module)]
        for module in usable:
            if module and module.order_number and is_wildcard(module.order_number):
                family_modules.add(module.order_number)

        interfaces = []
        for port in sorted(ports.values(), key=lambda p: p.subslot):
            kind, description = interface_type(port)
            interface = {"name": port_name.format(interface=port.interface, port=port.number), "type": kind}
            if description:
                interface["description"] = description
            interfaces.append(interface)

        for part_number in part_numbers:
            definition: dict = {
                "manufacturer": manufacturer,
                "model": clean_model(names, part_number),
                "slug": f"{slugify(manufacturer)}-{slugify(part_number)}",
                "part_number": part_number,
                "u_height": 0,
                "is_full_depth": False,
                "interfaces": [dict(interface) for interface in interfaces],
                "comments": source_note,
            }
            if newest.info and not per_interface:
                definition["description"] = _truncate(newest.info)
            if hardware and slots and bays != "none":
                if len(slots) <= max_bays:
                    definition["module-bays"] = [{"name": f"Slot {slot}", "position": str(slot)} for slot in slots]
                else:
                    result.notes.append(
                        f"{part_number}: {len(slots)} slots, more than the limit of {max_bays}; no module bays written"
                    )
            _apply_overlay(definition, overlays.get(part_number) or {})
            result.device_types.append(_ordered(definition, DEVICE_KEY_ORDER))
        for module in hardware:
            used_modules[module.order_number] = module

    if config.get("modules", True):
        device_parts = {definition["part_number"] for definition in result.device_types}
        for module in used_modules.values():
            part_number = normalise_order_number(module.order_number, gsd.vendor_id)
            if part_number in device_parts or _matches(config.get("exclude_modules"), part_number):
                continue
            definition = {
                "manufacturer": manufacturer,
                "model": part_number,
                "part_number": part_number,
                "comments": source_note,
            }
            description = module.info or module.name
            if description:
                definition["description"] = _truncate(description)
            _apply_overlay(definition, (config.get("module_types") or {}).get(part_number) or {})
            result.module_types.append(_ordered(definition, MODULE_KEY_ORDER))

    if family_modules:
        result.notes.append(
            f"{len(family_modules)} modules have a family pattern as order number "
            f"(for example {sorted(family_modules)[0]}) and are not written"
        )
    # NetBox wants a model to be unique per manufacturer: articles that share a
    # name (supply voltage variants, hardware revisions) get their part number added.
    models = [definition["model"] for definition in result.device_types]
    for definition in result.device_types:
        if models.count(definition["model"]) > 1 and definition["part_number"] not in definition["model"]:
            definition["model"] = f"{definition['model']} {definition['part_number']}"
    result.device_types.sort(key=lambda d: d["part_number"])
    result.module_types.sort(key=lambda d: d["part_number"])
    return result
