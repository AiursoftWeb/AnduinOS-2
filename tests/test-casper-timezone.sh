#!/bin/sh

set -eu

project_root=$(cd -- "$(dirname "$0")/.." && pwd)
timezone_script="$project_root/mods/46-casper-patch/14timezone"
test_root=$(mktemp -d)
trap 'rm -rf "$test_root"' EXIT HUP INT TERM

mkdir -p \
    "$test_root/target/usr/share/zoneinfo/Asia" \
    "$test_root/support"
: > "$test_root/target/usr/share/zoneinfo/Asia/Shanghai"

cat > "$test_root/support/casper-functions" <<'EOF'
log_begin_msg()
{
    :
}

log_end_msg()
{
    :
}
EOF

printf '%s\n' \
    'boot=casper locale=zh_CN.UTF-8 timezone=Asia/Shanghai quiet splash' \
    > "$test_root/cmdline"

CASPER_FUNCTIONS="$test_root/support/casper-functions" \
CASPER_CMDLINE_FILE="$test_root/cmdline" \
CASPER_TARGET_ROOT="$test_root/target" \
    sh "$timezone_script"

test "$(cat "$test_root/target/etc/timezone")" = "Asia/Shanghai"
test "$(readlink "$test_root/target/etc/localtime")" = \
    "/usr/share/zoneinfo/Asia/Shanghai"

rm -f "$test_root/target/etc/timezone" "$test_root/target/etc/localtime"
printf '%s\n' 'boot=casper timezone=../../etc/passwd' \
    > "$test_root/cmdline"

CASPER_FUNCTIONS="$test_root/support/casper-functions" \
CASPER_CMDLINE_FILE="$test_root/cmdline" \
CASPER_TARGET_ROOT="$test_root/target" \
    sh "$timezone_script"

test ! -e "$test_root/target/etc/timezone"
test ! -e "$test_root/target/etc/localtime"

echo "Casper timezone tests passed."
