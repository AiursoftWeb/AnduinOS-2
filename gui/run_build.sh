#!/bin/bash
# GUI 构建入口：以 root 运行（由 GUI 通过 sudo -S 调用）。
#
# 作用：
#   1. 补装缺失的构建依赖（原本由 make bootstrap 完成；GUI 直接调用 build.sh
#      绕过了 makefile 的 OS/root 检查，因此需要在这里补齐依赖安装）。
#   2. 随后把全部参数原样传给工程根目录的 build.sh。
#
# 用法： sudo -S -p "" ./gui/run_build.sh [--resume]
set -euo pipefail

HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(dirname "$HERE")"

# 与 makefile 中的 DEPS_COMMON 保持一致。
DEPS_COMMON=(
  binutils curl debootstrap fonts-unifont gnupg isomd5sum
  squashfs-tools sbsigntool xorriso grub2-common mtools dosfstools util-linux
)
HOST_ARCH="$(dpkg --print-architecture)"
if [[ "$HOST_ARCH" == "amd64" ]]; then
  DEPS_COMMON+=(grub-pc-bin)
fi

missing=()
for pkg in "${DEPS_COMMON[@]}"; do
  if [[ "$pkg" == "grub2-common" || "$pkg" == "grub-pc-bin" ]]; then
    if [[ "$(dpkg-query -W -f='${db:Status-Status}' anduinos-grub 2>/dev/null)" == "installed" ]]; then
      continue
    fi
  fi
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    missing+=("$pkg")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "[GUI] Installing missing build dependencies: ${missing[*]}"
  # 宿主系统的第三方源可能已损坏（例如 AnduinOS addon 缺少 Release 文件），
  # 此时 apt-get update 会返回非零。忽略该错误继续安装：apt 仍会从其余正常
  # 仓库安装缺失依赖，避免整个构建卡在依赖检查阶段。
  apt-get update -qq || echo "[GUI] apt update reported errors; continuing with available repositories."
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing[@]}"
else
  echo "[GUI] All required build packages are already installed."
fi

exec "$ROOT/build.sh" "$@"
