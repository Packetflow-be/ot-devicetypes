# ot-devicetypes

NetBox device types for industrial hardware: PLC I/O stations, drives, motor
starters, IO-Link masters. Generated from the device description files the
vendors already publish, in the format of the
[NetBox community device type library](https://github.com/netbox-community/devicetype-library).

The community library covers network and server hardware well and industrial
hardware barely: no Siemens, no WAGO, no Beckhoff. Writing those catalogues by
hand is not realistic. Every PROFINET device, however, ships with a GSDML file
that states its model, article number, Ethernet ports, slots and pluggable
modules. This project reads those files.

**Status: early.** The definitions here are skeletons: correct as far as they
go, and incomplete. See [What a definition contains](#what-a-definition-contains).

## What is in the repository

| Path | What |
|---|---|
| `device-types/`, `module-types/` | The definitions, same layout as the community library. Import them with any tool that reads that library. |
| `sources/` | One small file per GSDML file: which articles to write, and the facts the GSDML file does not hold. |
| `ot_devicetypes/` | The generator and the checker. |

Currently: Siemens (PN/PN Coupler, SINAMICS control units, SIMOCODE pro V PN),
WAGO 750 couplers and modules, Festo CTEU-PN, Murrelektronik MVK, ifm and
Turck IO-Link masters.

## What a definition contains

From the GSDML file:

- manufacturer, model and article number;
- the PROFINET ports, named `X1 P1`, `X1 P2`, `X2 P1`, with their medium
  (copper, fibre, 100 Mbit/s or 1 Gbit/s);
- module bays, for stations that take I/O modules;
- a module type for every module that has an article number of its own.

Not in a GSDML file, so missing until someone adds it to the source file:

- the power input;
- USB, serial and other non-PROFINET ports;
- weight and dimensions.

`ot-devicetypes check -v` lists the device types that still lack a power
input. The community library refuses those, so they are not yet offered there.

Devices that are not PROFINET devices have no GSDML file. That includes the
CPUs of the S7-1200 and S7-1500, which are controllers. They need another
source and are not covered yet.

## Use the generator

```sh
pip install git+https://github.com/Packetflow-be/ot-devicetypes
```

Look at what a file describes:

```sh
ot-devicetypes inspect GSDML-V2.34-Vendor-Device-20220126.xml
```

Convert one file as it is:

```sh
ot-devicetypes convert GSDML-V2.34-Vendor-Device-20220126.xml --out out/
```

Regenerate this library from a directory of GSDML files, then check it:

```sh
ot-devicetypes build --gsdml-dir ~/gsdml
ot-devicetypes check
```

GSDML files are not in this repository. They belong to their vendors; download
them from the vendor's support site. `build` skips a source whose file you do
not have and leaves its definitions as they are.

## Add a device

1. Download the GSDML file from the vendor.
2. Run `ot-devicetypes inspect` on it.
3. Add a file under `sources/`. [docs/sources.md](docs/sources.md) describes
   the format.
4. Run `ot-devicetypes build` and `ot-devicetypes check`.
5. Open a pull request with the source file and the generated definitions.

How the generator reads a GSDML file, and where it has to guess, is in
[docs/gsdml.md](docs/gsdml.md).

## Licence

The code is licensed under Apache-2.0 (`LICENSE`). The definitions in
`device-types/` and `module-types/` are dedicated to the public domain under
CC0 1.0 (`LICENSE-DATA`), the same as the community library, so they can be
contributed there. The JSON schema in `ot_devicetypes/schema/` is copied from
the community library (CC0 1.0).

Product names are trademarks of their owners. This project is not affiliated
with any of the manufacturers.
