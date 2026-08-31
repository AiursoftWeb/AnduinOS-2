#!/bin/bash

set -e
set -o pipefail
set -u

print_ok "Generating locales from SUPPORTED_LIVE_REGIONS..."

if [ -z "${SUPPORTED_LIVE_REGIONS:-}" ]; then
    print_error "SUPPORTED_LIVE_REGIONS is empty or not set — cannot generate locales"
    exit 1
fi

: > /etc/locale.gen
while IFS="|" read -r code _; do
    # trim whitespace that may trail the locale code
    code=$(printf '%s' "$code" | xargs)
    [ -z "$code" ] && continue
    if [[ "$code" =~ ^[a-z]{2}_[A-Z]{2}$ ]]; then
        echo "${code}.UTF-8 UTF-8" >> /etc/locale.gen
    else
        print_warn "Skipping malformed locale code from SUPPORTED_LIVE_REGIONS: '$code'"
    fi
done <<< "$SUPPORTED_LIVE_REGIONS"

if [ ! -s /etc/locale.gen ]; then
    print_error "No valid locales extracted from SUPPORTED_LIVE_REGIONS"
    exit 1
fi

locale-gen
judge "Generate locales from SUPPORTED_LIVE_REGIONS"
