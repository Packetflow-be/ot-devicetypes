"""Command line: inspect a GSDML file, build the library, check it."""

from __future__ import annotations

import argparse
import sys
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from . import __version__, gsdml, library
from .convert import Result, convert, is_wildcard, normalise_order_number


def find_gsdml(directory: Path, pattern: str) -> Path | None:
    """The newest file in `directory` whose name matches `pattern` (case-insensitive glob)."""
    pattern = pattern.casefold()
    matches = [path for path in directory.rglob("*") if path.is_file() and fnmatchcase(path.name.casefold(), pattern)]

    def rank(path: Path):
        schema, date = gsdml.file_metadata(path)
        return (date, tuple(int(part) for part in schema.split(".") if part.isdigit()), path.name)

    return max(matches, key=rank) if matches else None


def _write(result: Result, out: Path) -> tuple[int, int]:
    for definition in result.device_types:
        library.write(out, "device-types", definition)
    for definition in result.module_types:
        library.write(out, "module-types", definition)
    return len(result.device_types), len(result.module_types)


def _report(result: Result) -> None:
    for skipped in result.skipped:
        print(f"  skipped {skipped.order_number or '(none)'} ({skipped.name}): {skipped.reason}")
    for note in result.notes:
        print(f"  note    {note}")


def cmd_inspect(args: argparse.Namespace) -> int:
    for file in args.files:
        gsd = gsdml.parse(file)
        print(f"{gsd.path.name}: {gsd.vendor_name}, vendor 0x{gsd.vendor_id:04X}, device 0x{gsd.device_id:04X}")
        print(f"  {'order number':<24} {'ports':>5} {'slots':>5}  {'firmware':<16} name")
        for ap in gsd.access_points:
            order_number = normalise_order_number(ap.order_number, gsd.vendor_id)
            flag = "*" if is_wildcard(order_number) else " "
            print(
                f" {flag}{order_number:<24} {len(ap.ports):>5} {len(ap.slots):>5}  {ap.software_release:<16} {ap.name}"
            )
        hardware = [m for m in gsd.modules.values() if m.order_number and not is_wildcard(m.order_number)]
        print(f"  modules: {len(gsd.modules)} in the file, {len(hardware)} with an order number of their own")
        print("  (* = family pattern, needs an expand entry)")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    config = {"manufacturer": args.manufacturer} if args.manufacturer else {}
    result = convert(gsdml.parse(args.file), config)
    devices, modules = _write(result, Path(args.out))
    print(f"{Path(args.file).name}: {devices} device types, {modules} module types written to {args.out}")
    _report(result)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    out, gsdml_dir = Path(args.out), Path(args.gsdml_dir)
    missing = 0
    for source in sorted(Path(args.sources).glob("*.yaml")):
        config = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        file = find_gsdml(gsdml_dir, config.get("gsdml", ""))
        if not file:
            print(f"{source.name}: no file matching {config.get('gsdml')!r} in {gsdml_dir}, left as it is")
            missing += 1
            continue
        result = convert(gsdml.parse(file), config)
        devices, modules = _write(result, out)
        print(f"{source.name}: {file.name} -> {devices} device types, {modules} module types")
        _report(result)
    return 1 if missing and args.strict else 0


def cmd_check(args: argparse.Namespace) -> int:
    root = Path(args.root)
    findings = library.check(root)
    errors = [f for f in findings if f.level == "error"]
    upstream = [f for f in findings if f.level == "upstream"]
    for finding in errors + (upstream if args.upstream or args.verbose else []):
        print(f"{finding.level:<8} {finding.path.relative_to(root)}: {finding.message}")
    devices = len(library.definition_files(root, "device-types"))
    modules = len(library.definition_files(root, "module-types"))
    print(
        f"{devices} device types, {modules} module types: {len(errors)} errors, "
        f"{len(upstream)} device types not ready for the community library"
    )
    return 1 if errors or (args.upstream and upstream) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ot-devicetypes", description="NetBox device types for industrial hardware, from GSDML files."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="list what a GSDML file describes")
    inspect.add_argument("files", nargs="+")
    inspect.set_defaults(run=cmd_inspect)

    one = commands.add_parser("convert", help="convert one GSDML file without a source configuration")
    one.add_argument("file")
    one.add_argument("--out", default="out")
    one.add_argument("--manufacturer", help="manufacturer name to write (default: the vendor name in the file)")
    one.set_defaults(run=cmd_convert)

    build = commands.add_parser("build", help="regenerate the library from sources/*.yaml")
    build.add_argument("--gsdml-dir", required=True, help="directory holding the vendor's GSDML files")
    build.add_argument("--sources", default="sources")
    build.add_argument("--out", default=".")
    build.add_argument("--strict", action="store_true", help="fail when a source has no GSDML file")
    build.set_defaults(run=cmd_build)

    check = commands.add_parser("check", help="validate device-types/ and module-types/")
    check.add_argument("root", nargs="?", default=".")
    check.add_argument("--upstream", action="store_true", help="also fail on what the community library would refuse")
    check.add_argument("-v", "--verbose", action="store_true")
    check.set_defaults(run=cmd_check)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
