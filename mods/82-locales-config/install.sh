#!/bin/bash

set -e
set -o pipefail
set -u

print_ok "Generating locales from SUPPORTED_LOCALES..."

if [ -z "${SUPPORTED_LOCALES:-}" ]; then
    print_error "SUPPORTED_LOCALES is empty or not set — cannot generate locales"
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
        print_warn "Skipping malformed locale code from SUPPORTED_LOCALES: '$code'"
    fi
done <<< "$SUPPORTED_LOCALES"

if [ ! -s /etc/locale.gen ]; then
    print_error "No valid locales extracted from SUPPORTED_LOCALES"
    exit 1
fi

locale-gen
judge "Generate locales from SUPPORTED_LOCALES"
