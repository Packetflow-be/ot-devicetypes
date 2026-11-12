#!/bin/sh
# Refresh ot_devicetypes/schema/ from the NetBox community device type library.
set -eu
cd "$(dirname "$0")/../ot_devicetypes/schema"
repo=netbox-community/devicetype-library
sha=$(curl -fsSL "https://api.github.com/repos/$repo/commits/master" | sed -n 's/^  "sha": "\(.*\)",$/\1/p' | head -1)
[ -n "$sha" ] || { echo "could not read the latest commit of $repo" >&2; exit 1; }
for file in components devicetype generated_schema moduletype racktype reusable; do
    curl -fsSL "https://raw.githubusercontent.com/$repo/$sha/schema/$file.json" -o "$file.json"
done
sed -i "s/commit [0-9a-f]\{40\}/commit $sha/" UPSTREAM.md
echo "schema now at $repo@$sha"
