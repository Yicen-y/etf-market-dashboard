#!/usr/bin/env bash
# Code-only deployment. Explicit --apply is required; persistent data is never copied.
set -euo pipefail

usage() { echo "Usage: ETF_DATA_DIR=/persistent/data $0 PACKAGE.zip DEPLOY_ROOT SERVICE [--apply]"; exit 2; }
[[ $# -ge 3 && $# -le 4 ]] || usage
package=$(realpath -- "$1")
deploy_root=$(realpath -m -- "$2")
service=$3
mode=${4:-dry-run}
[[ "$mode" == "dry-run" || "$mode" == "--apply" ]] || usage
[[ -f "$package" && -d "$deploy_root" && -n "${ETF_DATA_DIR:-}" ]] || usage
data_root=$(realpath -- "$ETF_DATA_DIR")
[[ -d "$data_root" && "$data_root" != "$deploy_root" && "$data_root" != "$deploy_root"/* && "$deploy_root" != "$data_root"/* ]] || {
  echo "Data directory must exist outside the code deployment root" >&2; exit 2;
}
[[ "$service" =~ ^[a-zA-Z0-9_.@-]+$ ]] || usage
python3 - "$package" <<'PY'
import pathlib, stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = set()
    for info in archive.infolist():
        name = info.filename
        path = pathlib.PurePosixPath(name)
        mode = info.external_attr >> 16
        allowed = name in {'server.py', 'requirements.txt', 'README.md'} or path.parts[0] in {'scripts', 'web'}
        if (not name or '\\' in name or path.is_absolute() or '..' in path.parts
                or not allowed or name in names
                or stat.S_ISLNK(mode)):
            raise SystemExit(f'Unsafe archive entry: {name}')
        names.add(name)
    if 'server.py' not in names:
        raise SystemExit('Package missing server.py')
PY
stamp=$(date -u +%Y%m%dT%H%M%SZ)
release="$deploy_root/releases/$stamp"
echo "package=$package release=$release data=$data_root service=$service mode=$mode"
[[ "$mode" == "--apply" ]] || exit 0
previous=$(readlink -f "$deploy_root/current" || true)
before_snapshot=""
if [[ -n "$previous" ]]; then
  before_snapshot=$(curl --fail --silent --max-time 15 http://127.0.0.1:8000/api/snapshot | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot_id"])')
fi
[[ ! -e "$release" ]] || { echo "Release path already exists" >&2; exit 2; }
mkdir -p -- "$release"
unzip -q "$package" -d "$release"
python3 -m compileall -q "$release/server.py" "$release/scripts"
ln -s -- "$release" "$deploy_root/current.next"
mv -Tf -- "$deploy_root/current.next" "$deploy_root/current"
if ! systemctl restart "$service" || ! curl --fail --silent --max-time 15 http://127.0.0.1:8000/api/ready >/dev/null ||
   { [[ -n "$before_snapshot" ]] && [[ "$(curl --fail --silent --max-time 15 http://127.0.0.1:8000/api/snapshot | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot_id"])')" != "$before_snapshot" ]]; }; then
  echo "Health check failed; restoring prior code link" >&2
  if [[ -n "$previous" && -d "$previous" ]]; then
    ln -s -- "$previous" "$deploy_root/current.next"
    mv -Tf -- "$deploy_root/current.next" "$deploy_root/current"
    systemctl restart "$service" || true
  fi
  exit 1
fi
echo "Code deployed; data directory was not modified by this script"
