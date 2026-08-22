# Makefile —— AnduinOS build orchestrator
SHELL         := /usr/bin/env bash
.DEFAULT_GOAL := current

DEPS_COMMON := \
  binutils \
  curl \
  debootstrap \
  fonts-unifont \
  gnupg \
  squashfs-tools \
  xorriso \
  grub2-common \
  mtools \
  dosfstools

# Pick arch-specific GRUB packages at run time so the same Makefile works on
# both amd64 and arm64 build hosts. amd64 uses grub-pc-bin for its El Torito
# image; both architectures declare the signed GRUB and shim payloads directly
# because build.sh creates a Secure Boot capable removable EFI image.
DEPS_amd64 := \
  grub-pc-bin \
  grub-efi-amd64 \
  grub-efi-amd64-signed \
  shim-signed

DEPS_arm64 := \
  grub-efi-arm64 \
  grub-efi-arm64-signed \
  shim-signed

TARGET_ARCH ?= $(shell env -u TARGET_ARCH bash -c 'source ./args.sh; printf "%s\n" "$$TARGET_ARCH"')
DEPS := $(DEPS_COMMON) $(DEPS_$(TARGET_ARCH))

.PHONY: current clean bootstrap menuconfig buildtorrent test help

help:
	@echo "Usage:"
	@echo "  make          (or make current)   Build current language"
	@echo "  make menuconfig                   Configure build options (TUI)"
	@echo "  make clean                        Remove build artifacts"
	@echo "  make bootstrap                    Validate environment and deps"
	@echo "  make buildtorrent                 Generate torrents for dist/*.iso"
	@echo "  make test                         Test the newest ISO in dist/"
	@echo "  make test ISO=... ARCH=...        Test an explicit ISO"

bootstrap:
	@if [ "$$(id -u)" -eq 0 ]; then \
	  echo "Error: Do not run as root"; \
	  exit 1; \
	fi
	@if ! lsb_release -i | grep -qE "(Ubuntu|Debian|Tuxedo|Anduin)"; then \
	  echo "Error: Unsupported OS — only Ubuntu, Debian, Tuxedo or AnduinOS allowed"; \
	  exit 1; \
	fi
	@host=$$(lsb_release -cs); \
	target=$$(grep -oP 'export TARGET_UBUNTU_VERSION="\K[^"]+' args.sh); \
	if [ "$$host" != "$$target" ]; then \
	  echo "Error: Host codename '$$host' != target '$$target'"; \
	  echo "Build machine must run the same Ubuntu release as the target ISO."; \
	  exit 1; \
	fi
	@sudo -v

	@missing="" ; \
	for pkg in $(DEPS); do \
	  if ! dpkg -s $$pkg >/dev/null 2>&1; then \
	    missing="$$missing $$pkg"; \
	  fi; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo "Missing packages:$$missing"; \
	  echo "Installing missing dependencies..."; \
	  sudo apt-get update && sudo apt-get install -y$$missing; \
	else \
	  echo "[MAKE] All required packages are already installed."; \
	fi

menuconfig:
	@./menuconfig.sh

current: bootstrap
	@echo "[MAKE] Building current language..."
	@./build.sh

buildtorrent:
	@if [ ! -d dist ]; then \
	  echo "[ERROR] dist/ directory not found. Run 'make' first."; \
	  exit 1; \
	fi; \
	shopt -s nullglob; isos=(dist/*.iso); \
	if [ $${#isos[@]} -eq 0 ]; then \
	  echo "[ERROR] No ISO files found in dist/."; \
	  exit 1; \
	fi; \
	if ! command -v mktorrent &>/dev/null; then \
	  echo "[MAKE] Installing mktorrent..."; \
	  sudo apt-get update && sudo apt-get install -y mktorrent; \
	fi; \
	tracker=$$(mktemp); \
	curl -fsSL -o "$$tracker" https://raw.githubusercontent.com/ngosang/trackerslist/master/trackers_best.txt; \
	mapfile -t raw < "$$tracker"; \
	rm "$$tracker"; \
	announce_args=(); \
	for t in "$${raw[@]}"; do \
	  [ -n "$$t" ] && announce_args+=(-a "$$t"); \
	done; \
	for iso in "$${isos[@]}"; do \
	  base="$${iso%.iso}"; \
	  echo "[MAKE] Generating torrent for $$(basename "$$iso")..."; \
	  rm -f "$${base}.torrent"; \
	  mktorrent "$${announce_args[@]}" -o "$${base}.torrent" "$$iso"; \
	done; \
	echo "[MAKE] Torrent generation complete."

test:
	@PYTHONPATH=tests python3 -m unittest discover -s tests/unit -p 'test_*.py'
	@iso='$(ISO)'; arch='$(ARCH)'; \
	if [ -z "$$iso" ]; then \
		iso=$$(find dist -maxdepth 1 -type f -name '*.iso' -printf '%T@ %p\n' 2>/dev/null | sort -nr | sed -n '1s/^[^ ]* //p'); \
		if [ -z "$$iso" ]; then \
			echo "[ERROR] No ISO found in dist/. Build one or pass ISO=/path/to/image.iso"; \
			exit 2; \
		fi; \
		echo "[TEST] Auto-selected newest ISO: $$iso"; \
	fi; \
	if [ -z "$$arch" ]; then \
		case "$$(basename "$$iso")" in \
			*amd64*.iso) arch=amd64 ;; \
			*arm64*.iso|*aarch64*.iso) arch=arm64 ;; \
			*) echo "[ERROR] Cannot infer architecture from $$iso; pass ARCH=amd64|arm64"; exit 2 ;; \
		esac; \
	fi; \
	python3 tests/run.py --iso "$$iso" --arch "$$arch" \
		$(TEST_ARGS)

clean:
	@echo "[MAKE] Cleaning build artifacts..."
	@./clean_all.sh
	@echo "[MAKE] Clean complete."
