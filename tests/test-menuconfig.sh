#!/bin/bash

set -euo pipefail

project_root=$(cd -- "$(dirname "$0")/.." && pwd)
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

cp "$project_root/args.sh" "$test_root/args.sh"
cp "$project_root/menuconfig.sh" "$test_root/menuconfig.sh"

cat > "$test_root/fake-dialog" <<'EOF'
#!/bin/bash
set -euo pipefail

count=0
if [ -f "$FAKE_DIALOG_STATE" ]; then
    count=$(cat "$FAKE_DIALOG_STATE")
fi
count=$((count + 1))
printf '%s\n' "$count" > "$FAKE_DIALOG_STATE"

case "$count" in
1)
    printf '%s\n' build >&2
    ;;
2)
    printf '%s\n' interactive >&2
    ;;
3)
    # Answer "No" so INTERACTIVE becomes empty.
    exit 1
    ;;
4)
    printf '%s\n' back >&2
    ;;
5)
    printf '%s\n' "$FAKE_FINAL_ACTION" >&2
    ;;
*)
    # The Saved message box has no selection result.
    ;;
esac
EOF
chmod +x "$test_root/fake-dialog" "$test_root/menuconfig.sh"

cp "$test_root/args.sh" "$test_root/original-args.sh"
FAKE_DIALOG_STATE="$test_root/dialog-state" \
FAKE_FINAL_ACTION=exit \
DIALOG="$test_root/fake-dialog" \
    "$test_root/menuconfig.sh"
cmp "$test_root/original-args.sh" "$test_root/args.sh"

cp "$test_root/original-args.sh" "$test_root/args.sh"
: > "$test_root/dialog-state"
FAKE_DIALOG_STATE="$test_root/dialog-state" \
FAKE_FINAL_ACTION=save \
DIALOG="$test_root/fake-dialog" \
    "$test_root/menuconfig.sh"
grep -Fxq 'export INTERACTIVE=""' "$test_root/args.sh"

echo "Menuconfig transaction tests passed."
