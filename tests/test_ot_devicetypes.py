from pathlib import Path

import pytest
import yaml

from ot_devicetypes import cli, gsdml, library
from ot_devicetypes.convert import clean_model, convert, is_wildcard, normalise_order_number, slugify

FIXTURES = Path(__file__).parent / "fixtures"
ACME = FIXTURES / "GSDML-V2.35-Acme-Station-20240102.xml"


@pytest.fixture(scope="module")
def gsd():
    return gsdml.parse(ACME)


def by_part(definitions):
    return {definition["part_number"]: definition for definition in definitions}


# --- reading the file -------------------------------------------------------


def test_file_identity(gsd):
    assert (gsd.vendor_id, gsd.device_id) == (0xF001, 0x0001)
    assert gsd.vendor_name == "ACME Automation GmbH"
    assert (gsd.schema_version, gsd.release_date) == ("2.35", "20240102")
    assert len(gsd.access_points) == 7
    assert len(gsd.modules) == 4


def test_ports_carry_interface_and_port_number(gsd):
    x2 = next(ap for ap in gsd.access_points if ap.id == "DAP_GW_X2")
    assert [(p.interface, p.number) for p in x2.ports] == [(2, 1)]
    assert x2.ports[0].mau_types == (10, 11, 15, 16, 29, 30)


def test_mau_types_from_attribute_and_from_list(gsd):
    v11 = next(ap for ap in gsd.access_points if ap.id == "DAP_AC100_V11")
    assert [p.mau_types for p in v11.ports] == [(16,), (16, 30)]


@pytest.mark.parametrize(
    "value, expected",
    [("0..3", (1, 2, 3)), ("0 1 2", (1, 2)), ("1 4..6", (1, 4, 5, 6)), ("0", ()), (None, ()), ("junk", ())],
)
def test_parse_slots(value, expected):
    assert gsdml.parse_slots(value) == expected


def test_file_metadata_of_odd_names():
    assert gsdml.file_metadata(Path("gsdml-v2.3-turck-fen20_4iol-20211108-010714.xml")) == ("2.3", "20211108")
    assert gsdml.file_metadata(Path("gsdml.xml")) == ("", "")


# --- order numbers and names ------------------------------------------------


@pytest.mark.parametrize(
    "order_number, expected",
    [
        ("6ES7158-3AD01-0XA0", False),
        ("750-375/025-000", False),
        ("55562", False),
        ("ADAM-6100PN", False),
        ("Flexi-box 12", False),  # written in lower case, not a placeholder
        ("6SL32xx-xYxxx-xxFx", True),
        ("6SL3040-1MA01-0AA*", True),
        ("75x-400", True),
        ("", True),
    ],
)
def test_is_wildcard(order_number, expected):
    assert is_wildcard(order_number) is expected


def test_siemens_order_numbers_lose_the_catalogue_space():
    assert normalise_order_number("6ES7 158-3AD01-0XA0", 0x002A) == "6ES7158-3AD01-0XA0"
    assert normalise_order_number("  AB  12 ", 0x1234) == "AB 12"


def test_clean_model():
    assert clean_model(["750-375 V02.03.xx (FW 06)"], "750-375") == "750-375"
    assert clean_model(["PN/PN Coupler X1", "PN/PN Coupler X2"], "x") == "PN/PN Coupler"
    assert clean_model(["CU320-2 PN V4.4", "CU320-2 PN V5.2"], "x") == "CU320-2 PN"
    assert clean_model(["", ""], "AB-1") == "AB-1"


def test_slugify_follows_the_library_rule():
    assert slugify("750-375/025-000") == "750-375-025-000"
    assert slugify("GL.iNet v2.1") == "gl-inet-v2-1"


# --- conversion -------------------------------------------------------------


def test_one_device_type_per_article(gsd):
    result = convert(gsd)
    assert sorted(by_part(result.device_types)) == ["AC-100", "AC-900/025-000", "GW-200"]


def test_firmware_releases_merge_and_newest_wins(gsd):
    coupler = by_part(convert(gsd).device_types)["AC-100"]
    assert coupler["model"] == "AC-100 Coupler"
    assert coupler["slug"] == "acme-automation-gmbh-ac-100"
    assert coupler["interfaces"] == [
        {"name": "X1 P1", "type": "100base-tx"},
        {"name": "X1 P2", "type": "1000base-t"},  # V1.1 added gigabit
    ]
    assert coupler["description"] == "Fieldbus coupler PROFINET IO, 2 ports, up to 8 modules"
    assert (coupler["u_height"], coupler["is_full_depth"]) == (0, False)
    assert "GSDML-V2.35-Acme-Station-20240102.xml" in coupler["comments"]


def test_two_interfaces_become_one_device(gsd):
    gateway = by_part(convert(gsd).device_types)["GW-200"]
    assert gateway["model"] == "Network Gateway"
    assert [i["name"] for i in gateway["interfaces"]] == ["X1 P1", "X1 P2", "X2 P1"]
    assert gateway["interfaces"][2]["type"] == "1000base-t"
    assert "description" not in gateway  # each text covers one interface only
    assert "module-bays" not in gateway  # its "modules" are telegrams, not hardware


def test_module_bays_only_for_real_modules_and_within_the_limit(gsd):
    result = convert(gsd)
    devices = by_part(result.device_types)
    assert [bay["position"] for bay in devices["AC-100"]["module-bays"]] == [str(n) for n in range(1, 9)]
    assert "module-bays" not in devices["AC-900/025-000"]
    assert any("250 slots" in note for note in result.notes)
    assert "module-bays" in by_part(convert(gsd, {"module_bays": 300}).device_types)["AC-900/025-000"]
    assert "module-bays" not in by_part(convert(gsd, {"module_bays": "none"}).device_types)["AC-100"]


def test_fibre_and_unknown_media(gsd):
    interfaces = by_part(convert(gsd).device_types)["AC-900/025-000"]["interfaces"]
    assert interfaces[0] == {"name": "X1 P1", "type": "100base-fx"}
    assert interfaces[1]["type"] == "100base-fx" and "POF" in interfaces[1]["description"]
    assert interfaces[2] == {"name": "X1 P3", "type": "other", "description": "MAU type 99"}


def test_what_is_skipped_and_why(gsd):
    reasons = {skipped.order_number: skipped.reason for skipped in convert(gsd).skipped}
    assert "family pattern" in reasons["DRV 1xx-0AA*"]
    assert "pluggable adapter" in reasons["HD-300"]


def test_module_types_are_the_modules_with_an_article_number(gsd):
    result = convert(gsd)
    assert sorted(by_part(result.module_types)) == ["AM-DI8", "AM-DO8"]
    assert by_part(result.module_types)["AM-DO8"] == {
        "manufacturer": "ACME Automation GmbH",
        "model": "AM-DO8",
        "part_number": "AM-DO8",
        "description": "8 digital outputs, 24 V DC, 0.5 A",
        "comments": "Generated from GSDML-V2.35-Acme-Station-20240102.xml by ot-devicetypes.",
    }
    assert any("AM-AIx" in note for note in result.notes)
    assert convert(gsd, {"modules": False}).module_types == []


def test_source_configuration(gsd):
    config = {
        "manufacturer": "Acme",
        "port_name": "Port {port}",
        "exclude": ["^GW-"],
        "expand": {"DRV 1xx-0AA*": ["DRV 110-0AA0", "DRV 120-0AA0"]},
        "devices": {
            "AC-100": {
                "model": "AC-100",
                "set": {"weight": 0.2, "weight_unit": "kg"},
                "add": {
                    "power-ports": [{"name": "24V", "type": "dc-terminal"}],
                    "interfaces": [{"name": "Service", "type": "100base-tx", "mgmt_only": True}],
                },
            }
        },
    }
    result = convert(gsd, config)
    devices = by_part(result.device_types)
    assert "GW-200" not in devices
    coupler = devices["AC-100"]
    assert (coupler["manufacturer"], coupler["model"], coupler["slug"]) == ("Acme", "AC-100", "acme-ac-100")
    assert coupler["power-ports"] == [{"name": "24V", "type": "dc-terminal"}]
    assert [i["name"] for i in coupler["interfaces"]] == ["Port 1", "Port 2", "Service"]
    assert list(coupler).index("power-ports") < list(coupler).index("interfaces")  # library key order
    # Articles from one family share a name, so NetBox gets the part number in the model.
    assert devices["DRV 110-0AA0"]["model"] == "ACME Drive PN DRV 110-0AA0"
    assert devices["DRV 120-0AA0"]["slug"] == "acme-drv-120-0aa0"


def test_known_vendor_ids_get_a_plain_manufacturer_name(gsd):
    gsd_siemens = gsdml.parse(ACME)
    gsd_siemens.vendor_id = 0x002A
    assert convert(gsd_siemens).device_types[0]["manufacturer"] == "Siemens"


# --- writing and checking ---------------------------------------------------


def test_yaml_matches_the_library_style(gsd, tmp_path):
    coupler = by_part(convert(gsd, {"manufacturer": "Acme"}).device_types)["AC-100"]
    text = library.dump(coupler)
    assert text.startswith("---\nmanufacturer: Acme\nmodel: AC-100 Coupler\n")
    assert "interfaces:\n  - name: X1 P1\n    type: 100base-tx\n" in text
    assert "    position: '1'\n" in text
    assert yaml.safe_load(text) == coupler


def test_generated_library_passes_the_check(gsd, tmp_path):
    result = convert(gsd, {"manufacturer": "Acme"})
    for definition in result.device_types:
        library.write(tmp_path, "device-types", definition)
    for definition in result.module_types:
        library.write(tmp_path, "module-types", definition)
    assert (tmp_path / "device-types/Acme/ac-900-025-000.yaml").exists()  # '/' cannot be in a file name
    findings = library.check(tmp_path)
    assert [f for f in findings if f.level == "error"] == []
    # No power input in a GSDML file: the two types without module bays are flagged.
    assert sorted(f.path.name for f in findings if f.level == "upstream") == ["GW-200.yaml", "ac-900-025-000.yaml"]


def test_check_finds_broken_definitions(tmp_path):
    good = {
        "manufacturer": "Acme",
        "model": "A1",
        "slug": "acme-a1",
        "part_number": "A1",
        "u_height": 0,
        "is_full_depth": False,
        "power-ports": [{"name": "24V", "type": "dc-terminal"}],
    }
    library.write(tmp_path, "device-types", good)
    cases = {
        "wrong-name.yaml": dict(good, model="A2", slug="acme-a2", part_number="A2"),
        "A3.yaml": dict(good, model="A3", slug="other-a3", part_number="A3"),
        "A4.yaml": dict(good, model="A4", slug="acme-a1", part_number="A4"),
        "A5.yaml": dict(good, model="A5", slug="acme-a5", part_number="A5", interfaces=[{"name": "X1"}]),
        "A6.yaml": dict(
            good,
            model="A6",
            slug="acme-a6",
            part_number="A6",
            interfaces=[{"name": "X1", "type": "100base-tx"}, {"name": "X1", "type": "100base-tx"}],
        ),
        "A7.yaml": dict(good, slug="acme-a7", part_number="A7", model="A1"),
    }
    for name, definition in cases.items():
        (tmp_path / "device-types/Acme" / name).write_text(library.dump(definition))
    messages: dict[str, str] = {}
    for finding in library.check(tmp_path):
        if finding.level == "error":
            messages[finding.path.name] = messages.get(finding.path.name, "") + finding.message + "\n"
    assert "file name" in messages["wrong-name.yaml"]
    assert "start with the manufacturer" in messages["A3.yaml"]
    assert "also used by" in messages["A4.yaml"]
    assert "schema" in messages["A5.yaml"]
    assert "more than once" in messages["A6.yaml"]
    assert 'model "A1" is also used' in messages["A7.yaml"]
    assert "A1.yaml" not in messages


# --- command line -----------------------------------------------------------


def test_newest_gsdml_file_wins(tmp_path):
    for name in (
        "GSDML-V2.25-Acme-Station-20240102.xml",
        "GSDML-V2.35-Acme-Station-20240102.xml",
        "gsdml-v2.35-acme-station-20230505.xml",
        "GSDML-V2.35-Other-Thing-20250101.xml",
    ):
        (tmp_path / name).write_text("")
    assert cli.find_gsdml(tmp_path, "gsdml-*-acme-station-*.xml").name == "GSDML-V2.35-Acme-Station-20240102.xml"
    assert cli.find_gsdml(tmp_path, "gsdml-*-nothing-*.xml") is None


def test_build_and_check_from_the_command_line(tmp_path, capsys):
    sources = tmp_path / "sources"
    sources.mkdir()
    (sources / "acme.yaml").write_text(
        yaml.safe_dump(
            {
                "gsdml": "gsdml-*-acme-station-*.xml",
                "manufacturer": "Acme",
                "devices": {
                    "GW-200": {"add": {"power-ports": [{"name": "24V", "type": "dc-terminal"}]}},
                    "AC-900/025-000": {"add": {"power-ports": [{"name": "24V", "type": "dc-terminal"}]}},
                },
            }
        )
    )
    (sources / "absent.yaml").write_text("gsdml: gsdml-*-absent-*.xml\n")
    arguments = ["build", "--gsdml-dir", str(FIXTURES), "--sources", str(sources), "--out", str(tmp_path)]
    assert cli.main(arguments) == 0
    assert cli.main(arguments + ["--strict"]) == 1
    output = capsys.readouterr().out
    assert "acme.yaml: GSDML-V2.35-Acme-Station-20240102.xml -> 3 device types, 2 module types" in output
    assert "skipped HD-300" in output and "absent.yaml: no file matching" in output

    assert cli.main(["check", str(tmp_path), "--upstream"]) == 0
    assert "3 device types, 2 module types: 0 errors, 0 device types not ready" in capsys.readouterr().out


def test_inspect_lists_access_points(capsys):
    assert cli.main(["inspect", str(ACME)]) == 0
    output = capsys.readouterr().out
    assert "vendor 0xF001" in output
    assert "*DRV 1xx-0AA*" in output
    assert "4 in the file, 2 with an order number of their own" in output
