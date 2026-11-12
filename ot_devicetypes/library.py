"""Read, write and check definitions in the community library's layout.

    device-types/<Manufacturer>/<part number>.yaml
    module-types/<Manufacturer>/<part number>.yaml

`check` applies the library's JSON schema plus the rules its test suite
enforces on a pull request (slug, file name, unique component names, power
source), so a definition that passes here should pass there.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .convert import slugify

COMPONENT_KEYS = (
    "console-ports",
    "console-server-ports",
    "power-ports",
    "power-outlets",
    "interfaces",
    "front-ports",
    "rear-ports",
    "device-bays",
    "module-bays",
)
KINDS = {"device-types": "devicetype.json", "module-types": "moduletype.json"}
_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


class _Dumper(yaml.SafeDumper):
    # The library indents list items under their key.
    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def dump(definition: dict) -> str:
    return "---\n" + yaml.dump(
        definition, Dumper=_Dumper, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1000
    )


def filename(definition: dict) -> str:
    part_number = definition.get("part_number") or definition["model"]
    stem = part_number if _SAFE_FILENAME.match(part_number) else slugify(part_number)
    return f"{stem}.yaml"


def write(root: Path, kind: str, definition: dict) -> Path:
    path = Path(root) / kind / definition["manufacturer"] / filename(definition)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(definition), encoding="utf-8")
    return path


def load(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def definition_files(root: Path, kind: str) -> list[Path]:
    return sorted(p for p in (Path(root) / kind).glob("*/*") if p.suffix in (".yaml", ".yml"))


@dataclass
class Finding:
    path: Path
    level: str  # "error": not a valid definition; "upstream": valid, but the community library would refuse it
    message: str


def _validators() -> dict[str, Draft202012Validator]:
    schema_dir = resources.files("ot_devicetypes") / "schema"
    registry = Registry()
    schemas = {}
    for entry in schema_dir.iterdir():
        if entry.name.endswith(".json"):
            schemas[entry.name] = json.loads(entry.read_text(encoding="utf-8"), parse_float=Decimal)
            registry = Resource.from_contents(schemas[entry.name]) @ registry
    return {kind: Draft202012Validator(schemas[name], registry=registry) for kind, name in KINDS.items()}


def has_power_source(definition: dict) -> bool:
    """The library's rule for 'this device type says where its power comes from'."""
    if definition.get("power-ports") or definition.get("module-bays"):
        return True
    if any(interface.get("poe_mode") == "pd" for interface in definition.get("interfaces") or []):
        return True
    for key in ("console-ports", "rear-ports"):
        if any(port.get("_is_power_source") for port in definition.get(key) or []):
            return True
    return definition.get("subdevice_role") == "child" or definition.get("is_powered") is False


def check(root: Path) -> list[Finding]:
    root = Path(root)
    findings: list[Finding] = []
    validators = _validators()
    slugs: dict[str, Path] = {}
    models: dict[tuple[str, str, str], Path] = {}
    module_files: dict[str, Path] = {}

    for kind in KINDS:
        for path in definition_files(root, kind):
            try:
                definition = load(path)
            except yaml.YAMLError as error:
                findings.append(Finding(path, "error", f"not valid YAML: {error}"))
                continue
            if not isinstance(definition, dict):
                findings.append(Finding(path, "error", "not a mapping"))
                continue
            for error in sorted(validators[kind].iter_errors(definition), key=lambda e: list(e.absolute_path)):
                where = "/".join(str(part) for part in error.absolute_path) or "(top level)"
                findings.append(Finding(path, "error", f"schema: {where}: {error.message}"))

            manufacturer = definition.get("manufacturer", "")
            if path.parent.name != manufacturer:
                findings.append(Finding(path, "error", f'directory must be the manufacturer "{manufacturer}"'))

            model_slug = slugify(str(definition.get("model", "")))
            part_number = str(definition.get("part_number", ""))
            part_slug = slugify(part_number)
            stem = path.stem.casefold()
            if stem not in {model_slug, part_slug, part_number.casefold()} - {""}:
                findings.append(Finding(path, "error", "file name must be the model or the part number"))

            model_key = (kind, manufacturer, str(definition.get("model", "")))
            if model_key in models:
                findings.append(Finding(path, "error", f'model "{model_key[2]}" is also used by {models[model_key]}'))
            models.setdefault(model_key, path)

            for key in COMPONENT_KEYS:
                names = [component.get("name") for component in definition.get(key) or []]
                for name in sorted({name for name in names if names.count(name) > 1}):
                    findings.append(Finding(path, "error", f'{key}: name "{name}" is used more than once'))

            if kind == "device-types":
                slug = definition.get("slug", "")
                if slug in slugs:
                    findings.append(Finding(path, "error", f'slug "{slug}" is also used by {slugs[slug]}'))
                slugs.setdefault(slug, path)
                if not slug.startswith(slugify(manufacturer)):
                    findings.append(Finding(path, "error", "slug must start with the manufacturer"))
                if not any(slug.endswith(end) for end in (model_slug, part_slug) if end):
                    findings.append(Finding(path, "error", "slug must end with the model or the part number"))
                if definition.get("subdevice_role") == "child" and definition.get("u_height") != 0:
                    findings.append(Finding(path, "error", "a child device must have u_height 0"))
                if not has_power_source(definition):
                    findings.append(
                        Finding(path, "upstream", "no power source: add power-ports in the source configuration")
                    )
            else:
                if stem in module_files:
                    findings.append(Finding(path, "error", f"same file name as {module_files[stem]}"))
                module_files.setdefault(stem, path)
    return findings
