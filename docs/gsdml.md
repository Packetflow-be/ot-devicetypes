# How a GSDML file becomes a device type

A GSDML file is the XML description a PROFINET controller's engineering tool
needs to configure a device. It is written for that tool, not for an
inventory, so the generator has to interpret it. This page lists each
decision.

## What is read

| GSDML | Becomes |
|---|---|
| `DeviceAccessPointItem` (the head of a station) | a device type |
| its `ModuleInfo/OrderNumber` | `part_number`, the file name and the slug |
| its `ModuleInfo/Name` | `model`, without the firmware version |
| its `ModuleInfo/InfoText` | `description`, cut to 200 characters |
| `PortSubmoduleItem` | an interface |
| `PhysicalSlots` | module bays |
| `ModuleItem` with an order number | a module type |

Everything else (parameters, telegrams, I/O data, diagnostics) is ignored.

## Decisions

**One article, many entries.** A file lists a device once per firmware
release. Entries with the same order number become one device type. Where they
disagree about a port, the entry that comes last in the file wins, since
vendors append new firmware at the end.

**One box, two interfaces.** A device with two PROFINET interfaces, such as a
PN/PN coupler, is listed once per interface under the same order number. The
port's subslot number says which interface it belongs to (`0x8001` is X1 P1,
`0x8101` is X2 P1), so the entries merge into one device type with ports on
X1 and X2. The description is left out then, because each entry's text
describes one half.

**Family patterns.** Drives and motor starters often carry a pattern
(`6SL32xx-xYxxx-xxFx`, `3UF7011-1A*00-0`) where an article number should be.
A device type needs a real article, so a pattern is skipped unless the source
file lists the articles it stands for. A `*`, a `?`, or a lower-case `x` as
the only lower-case letter marks a pattern.

**Logical modules.** Many "modules" in a file are telegrams or data layouts,
not hardware. Only a module with an order number of its own becomes a module
type, and a station only gets module bays when at least one such module fits
in it.

**Many slots.** A station with more slots than the limit (64 by default) gets
no module bays; the generator prints a note. Two hundred and fifty empty bays
help nobody.

**Pluggable ports.** Some head stations take their Ethernet ports from a
pluggable adapter. They have no fixed port in the file and are skipped.

**Media.** A port lists the media it supports as IANA MAU types. The fastest
one decides the interface type:

| MAU type | Interface type |
|---|---|
| 15, 16 | `100base-tx` |
| 17, 18 | `100base-fx` |
| 54 (POF/PCF fibre) | `100base-fx`, with a description |
| 29, 30 | `1000base-t` |
| 23, 24 | `1000base-lx` |
| 25, 26 | `1000base-sx` |
| anything else | `other`, with the MAU type in the description |

A port that names no MAU type is 100BASE-TX, the GSDML default.

**Siemens article numbers.** Siemens writes `6ES7 158-3AD01-0XA0` in
catalogues and `6ES7158-3AD01-0XA0` in its web shop. The space is removed.

**Rack units.** Every device type gets `u_height: 0`: this hardware sits on a
DIN rail or a machine, not in a 19-inch rack.

## What a GSDML file cannot tell

The power input, USB and serial ports, a second Ethernet port that is not
PROFINET, weight and dimensions. These come from the data sheet, through the
source file ([sources.md](sources.md)).
