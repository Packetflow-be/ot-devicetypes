"""Import every definition into a real NetBox, the way a user would.

Each file is posted to NetBox's own import page (Device types > Import, YAML),
then the stored objects are compared with the file. Run from NetBox's
`netbox/` directory, with the library root as argument, on a migrated,
throwaway database.
"""

import os
import sys
from pathlib import Path

import django
import yaml

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "netbox.settings")
django.setup()

from dcim.models import DeviceType, Manufacturer, ModuleType  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment  # noqa: E402
from django.utils.text import slugify  # noqa: E402

# Component key in a definition -> name of the related manager on the stored type.
COMPONENTS = {
    "console-ports": "consoleporttemplates",
    "console-server-ports": "consoleserverporttemplates",
    "power-ports": "powerporttemplates",
    "power-outlets": "poweroutlettemplates",
    "interfaces": "interfacetemplates",
    "front-ports": "frontporttemplates",
    "rear-ports": "rearporttemplates",
    "module-bays": "modulebaytemplates",
    "device-bays": "devicebaytemplates",
}
KINDS = {
    "device-types": ("/dcim/device-types/import/", DeviceType),
    "module-types": ("/dcim/module-types/import/", ModuleType),
}


def errors_of(response) -> str:
    form = (response.context or {}).get("form") if response.context else None
    if form is not None and form.errors:
        return "; ".join(f"{field}: {' '.join(messages)}" for field, messages in form.errors.items())
    return f"HTTP {response.status_code}"


def main(root: Path) -> int:
    setup_test_environment()  # makes response.context available
    user = get_user_model().objects.create_superuser("import-test", "import-test@example.com", "not-a-secret")
    client = Client()
    client.force_login(user)

    failures = []
    imported = {kind: 0 for kind in KINDS}
    for kind, (url, model) in KINDS.items():
        for path in sorted((root / kind).glob("*/*.y*ml")):
            text = path.read_text(encoding="utf-8")
            definition = yaml.safe_load(text)
            Manufacturer.objects.get_or_create(
                name=definition["manufacturer"], defaults={"slug": slugify(definition["manufacturer"])}
            )
            response = client.post(url, {"import_method": "direct", "format": "yaml", "data": text})
            if response.status_code != 302:
                failures.append(f"{path.relative_to(root)}: not imported: {errors_of(response)}")
                continue
            stored = model.objects.get(manufacturer__name=definition["manufacturer"], model=definition["model"])
            for field in ("slug", "part_number", "u_height", "is_full_depth", "description"):
                value = getattr(stored, field, None)
                if field in definition and value != definition[field]:
                    failures.append(f"{path.relative_to(root)}: {field} is {value!r}, file says {definition[field]!r}")
            for key, manager in COMPONENTS.items():
                if not hasattr(stored, manager):
                    continue
                expected = sorted(component["name"] for component in definition.get(key) or [])
                found = sorted(getattr(stored, manager).values_list("name", flat=True))
                if expected != found:
                    failures.append(f"{path.relative_to(root)}: {key} are {found}, file says {expected}")
            imported[kind] += 1

    for failure in failures:
        print(f"FAIL {failure}")
    print(
        f"imported {imported['device-types']} device types and {imported['module-types']} module types "
        f"into NetBox {django.conf.settings.RELEASE.version}: {len(failures)} failures"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
