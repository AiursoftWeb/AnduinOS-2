#!/bin/bash

set -e                  # exit on error
set -o pipefail         # exit on pipeline error
set -u                  # treat unset variable as error

print_ok "Configuring machine id..."
dbus-uuidgen > /etc/machine-id
install -d /var/lib/dbus
ln -fs /etc/machine-id /var/lib/dbus/machine-id
judge "Configure machine id"
