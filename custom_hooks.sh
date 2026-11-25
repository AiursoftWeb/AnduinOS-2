#!/bin/bash
# ============================================================================
# 自定义 chroot 脚本（由图形配置器「自定义脚本」页面管理）
# 执行时机：所有 mods 执行完毕之后、卸载 chroot 之前。
# 执行环境：以 root 身份在 chroot 内运行，工作目录为 /。
# 说明：在这里可以安装额外软件、修改系统配置、添加文件等。
#       脚本内容由 UI 保存，重新生成构建时会被复制到 chroot 内执行。
# 示例：
#   apt install -y htop neofetch
#   echo "my-anduinos" > /etc/hostname
#   printf 'Hello from custom hook\n' > /etc/motd
# ============================================================================

echo "[CUSTOM] chroot hook started"
# 在此添加你的自定义命令
echo "[CUSTOM] chroot hook finished"
