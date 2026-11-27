#!/bin/bash
# ============================================================================
# 自定义打包前脚本（由图形配置器「自定义脚本」页面管理）
# 执行时机：image/ 目录已生成（含 rootfs.squashfs、内核、GRUB 配置等），
#           但尚未调用 xorriso 打包成 ISO 之前。
# 执行环境：在宿主机以构建用户身份运行，工作目录为工程根目录。
# 可用变量：SCRIPT_DIR, TARGET_NAME, TARGET_BUSINESS_NAME, TARGET_BUILD_VERSION,
#           TARGET_ARCH, APT_CACHE_DIR 等（由 build.sh 导出）。
# 说明：可在这里向 image/ 添加文件或修改 ISO 内容。
# 示例：
#   echo "custom build" > image/.disk/custom
#   cp my-wallpaper.png image/
# ============================================================================

echo "[CUSTOM] pre-ISO hook started"
# 在此添加你的自定义命令
echo "[CUSTOM] pre-ISO hook finished"
