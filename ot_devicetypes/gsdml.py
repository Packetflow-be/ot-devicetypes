"""Read a PROFINET GSDML file into a small, vendor-neutral model.

Only the parts that describe hardware are read: the device access points
(the head of a station: a coupler, a drive control unit, a compact I/O block),
their fixed Ethernet ports, their slots, and the modules that can be plugged
into those slots. Parameters, telegrams and diagnostics are ignored.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# A GSDML file name ends in the release date: GSDML-V2.34-Vendor-Device-20220126.xml
# (optionally followed by -hhmmss).
_FILENAME = re.compile(r"gsdml-v(?P<schema>\d+(?:\.\d+)*)-.*?-(?P<date>\d{8})(?:-\d{6})?\.xml$", re.IGNORECASE)

# Subslot numbers 0x8000..0x8FFF describe the PROFINET interface itself:
# 0x8IPP, with I the interface index (0 = X1) and PP the port (0 = the interface).
_PDEV_BASE = 0x8000


@dataclass(frozen=True)
class Port:
    interface: int  # 1 = X1
    number: int  # 1 = P1
    subslot: int
    mau_types: tuple[int, ...]  # IANA MAU types; (16,) = 100BASE-TX full duplex
    label: str = ""


@dataclass
class AccessPoint:
    id: str
    name: str
    info: str
    order_number: str
    vendor: str
    hardware_release: str
    software_release: str
    slots: tuple[int, ...]  # slot numbers a module can go in (slot 0, the access point, is left out)
    ports: list[Port] = field(default_factory=list)
    module_ids: list[str] = field(default_factory=list)  # modules usable in this access point
    position: int = 0  # order in the file; later entries are newer firmware


@dataclass
class Module:
    id: str
    name: str
    info: str
    order_number: str
    vendor: str
    category: str = ""


@dataclass
class GsdFile:
    path: Path
    schema_version: str
    release_date: str  # YYYYMMDD, from the file name ("" if the name is non-standard)
    vendor_id: int
    device_id: int
    vendor_name: str
    access_points: list[AccessPoint]
    modules: dict[str, Module]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element if _local(child.tag) == name]


def _descendants(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in element.iter() if _local(child.tag) == name]


def _int(value: str | None, default: int = 0) -> int:
    if not value:
        return default
    try:
        return int(value, 0)
    except ValueError:
        return default


def parse_slots(value: str | None) -> tuple[int, ...]:
    """'0..16' or '1 2 5..7' -> the slot numbers, without slot 0."""
    slots: set[int] = set()
    for part in (value or "").split():
        low, _, high = part.partition("..")
        try:
            first, last = int(low), int(high or low)
        except ValueError:
            continue
        slots.update(range(first, last + 1))
    slots.discard(0)
    return tuple(sorted(slots))


def _mau_types(port: ET.Element) -> tuple[int, ...]:
    found: list[int] = []
    for token in re.split(r"[;\s]+", port.get("MAUTypes") or ""):
        if token.isdigit():
            found.append(int(token))
    for item in _descendants(port, "MAUTypeItem"):
        if (item.get("Value") or "").isdigit():
            found.append(int(item.get("Value")))
    # The GSDML specification's default when a port names no MAU type.
    return tuple(dict.fromkeys(found)) or (16,)


def file_metadata(path: Path) -> tuple[str, str]:
    """(schema version, release date) from the file name."""
    match = _FILENAME.search(path.name)
    return (match["schema"], match["date"]) if match else ("", "")


def parse(path: str | Path) -> GsdFile:
    path = Path(path)
    root = ET.parse(path).getroot()

    texts: dict[str, str] = {}
    for language in _descendants(root, "PrimaryLanguage"):
        for text in language:
            if text.get("TextId"):
                texts[text.get("TextId")] = (text.get("Value") or "").strip()

    def info_of(item: ET.Element) -> dict[str, str]:
        result: dict[str, str] = {}
        for module_info in _children(item, "ModuleInfo"):
            if module_info.get("CategoryRef"):
                result["Category"] = module_info.get("CategoryRef")
            for entry in module_info:
                key = _local(entry.tag)
                if entry.get("TextId"):
                    result[key] = texts.get(entry.get("TextId"), "")
                else:
                    result[key] = (entry.get("Value") or "").strip()
        return result

    identity = (_descendants(root, "DeviceIdentity") or [ET.Element("DeviceIdentity")])[0]
    vendor_names = [e.get("Value") for e in _descendants(identity, "VendorName") if e.get("Value")]
    file_vendor = vendor_names[0].strip() if vendor_names else ""

    modules: dict[str, Module] = {}
    for item in _descendants(root, "ModuleItem"):
        info = info_of(item)
        modules[item.get("ID", "")] = Module(
            id=item.get("ID", ""),
            name=info.get("Name", ""),
            info=info.get("InfoText", ""),
            order_number=info.get("OrderNumber", ""),
            vendor=info.get("VendorName", "") or file_vendor,
            category=info.get("Category", ""),
        )

    access_points: list[AccessPoint] = []
    for position, item in enumerate(_descendants(root, "DeviceAccessPointItem")):
        info = info_of(item)
        ports: list[Port] = []
        for submodules in _children(item, "SystemDefinedSubmoduleList"):
            for port in _children(submodules, "PortSubmoduleItem"):
                subslot = _int(port.get("SubslotNumber"))
                if subslot <= _PDEV_BASE:
                    continue
                ports.append(
                    Port(
                        interface=((subslot - _PDEV_BASE) >> 8) + 1,
                        number=subslot & 0xFF,
                        subslot=subslot,
                        mau_types=_mau_types(port),
                        label=texts.get(port.get("TextId", ""), ""),
                    )
                )
        module_ids = [
            ref.get("ModuleItemTarget", "")
            for usable in _children(item, "UseableModules")
            for ref in _children(usable, "ModuleItemRef")
        ]
        access_points.append(
            AccessPoint(
                id=item.get("ID", ""),
                name=info.get("Name", ""),
                info=info.get("InfoText", ""),
                order_number=info.get("OrderNumber", ""),
                vendor=info.get("VendorName", "") or file_vendor,
                hardware_release=info.get("HardwareRelease", ""),
                software_release=info.get("SoftwareRelease", ""),
                slots=parse_slots(item.get("PhysicalSlots")),
                ports=sorted(ports, key=lambda p: p.subslot),
                module_ids=module_ids,
                position=position,
            )
        )

    schema_version, release_date = file_metadata(path)
    return GsdFile(
        path=path,
        schema_version=schema_version,
        release_date=release_date,
        vendor_id=_int(identity.get("VendorID")),
        device_id=_int(identity.get("DeviceID")),
        vendor_name=file_vendor,
        access_points=access_points,
        modules=modules,
    )
