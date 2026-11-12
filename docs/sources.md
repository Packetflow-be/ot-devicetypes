# Source files

A source file in `sources/` tells the generator which GSDML file to read and
adds what that file does not hold. Only `gsdml` is required.

```yaml
# Which file. A case-insensitive glob on the file name; when several files
# match, the newest release date wins, then the newest GSDML schema version.
gsdml: "gsdml-v*-acme-station-*.xml"

# Manufacturer name to write. Without it: a built-in name for known PROFINET
# vendor IDs, else the vendor name in the file.
manufacturer: Acme

# Name of each port. {interface} and {port} are numbers, starting at 1.
port_name: "X{interface} P{port}"      # the default

# Module bays on stations that take modules: "auto" (the default) writes one
# bay per slot for up to 64 slots, a number sets another limit, "none" writes
# no bays.
module_bays: auto

# Write a module type for each module with an article number. Default true.
modules: true

# Regular expressions on the article number. `include` keeps only matches,
# `exclude` drops matches, `exclude_modules` does the same for module types.
include: ["^AC-"]
exclude: ["^AC-9"]
exclude_modules: ["^AM-X"]

# A GSDML file often gives a pattern in place of an article number
# ("6SL3040-1MA01-0AA*"). List the real articles the pattern stands for; one
# device type is written for each. Without an entry the pattern is skipped.
expand:
  "DRV 1xx-0AA*": ["DRV 110-0AA0", "DRV 120-0AA0"]

# Per article: a better model name, top-level fields to set, components to add.
devices:
  AC-100:
    model: AC-100
    set:
      weight: 0.2
      weight_unit: kg
    add:
      power-ports:
        - name: 24V
          type: dc-terminal
      console-ports:
        - name: USB
          type: usb-micro-b

# The same for module types.
module_types:
  AM-DI8:
    set:
      description: 8 digital inputs, 24 V DC
```

`set` and `add` take the field names and values of the
[community library](https://github.com/netbox-community/devicetype-library);
`ot-devicetypes check` validates the result against its schema.

## Rules for what goes in a source file

- Take every fact you add from the manufacturer's data sheet or manual, and
  say which one in a comment.
- Only list an article under `expand` when you have seen that article number
  in the manufacturer's catalogue.
- A model name must be unique per manufacturer. When several articles share a
  name, the generator appends the article number; set `model` if you know a
  better name.
