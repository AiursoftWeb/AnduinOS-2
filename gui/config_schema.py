#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""config_schema.py — GUI 配置项的元数据定义（分组、控件类型、选项、说明）。

每个分组与字段都带有 ``label_key`` / ``help_key``，指向 i18n 词条；原有的
中文 ``label`` / ``help`` 文本保留作为译文缺失时的兜底。
"""

from __future__ import annotations


CODES = [
    "jammy", "noble", "oracular", "plucky", "questing", "resolute",
]

ARCHES = ["amd64", "arm64"]

APKG_SERVERS = [
    "https://packages.anduinos.com",
    "https://apkg-dev.aiursoft.com",
]

APT_CONFIG_PACKAGES = [
    "anduinos-apt-config",
    "anduinos-apt-config-dev",
]

SECTIONS = [
    {
        "id": "os",
        "label": "系统信息",
        "label_key": "section.os",
        "items": [
            {
                "key": "TARGET_UBUNTU_VERSION",
                "label": "Ubuntu 版本代号",
                "label_key": "field.ubuntu_version",
                "type": "combo",
                "options": CODES,
                "help": "目标 Ubuntu 套件代号。构建主机的代号必须与之匹配。",
                "help_key": "help.ubuntu_version",
            },
            {
                "key": "TARGET_NAME",
                "label": "系统短名称",
                "label_key": "field.target_name",
                "type": "text",
                "help": "小写、无空格与特殊字符，例如 anduinos。会用作 ISO 内的标识文件与输出文件名。",
                "help_key": "help.target_name",
            },
            {
                "key": "TARGET_BUSINESS_NAME",
                "label": "系统显示名称",
                "label_key": "field.business_name",
                "type": "text",
                "help": "发行版的展示名称，例如 AnduinOS。",
                "help_key": "help.business_name",
            },
            {
                "key": "TARGET_BUILD_VERSION",
                "label": "构建版本号",
                "label_key": "field.build_version",
                "type": "text",
                "help": "版本字符串，格式 x.y.z（可带 -beta1 等后缀），例如 2.0.5。",
                "help_key": "help.build_version",
            },
        ],
    },
    {
        "id": "repos",
        "label": "软件源",
        "label_key": "section.repos",
        "items": [
            {
                "key": "APT_SOURCE",
                "label": "Ubuntu APT 镜像",
                "label_key": "field.apt_source",
                "type": "text",
                "help": "组装根文件系统所用的 Ubuntu 镜像地址，可替换为任意可用镜像。",
                "help_key": "help.apt_source",
            },
            {
                "key": "APKG_SERVER",
                "label": "AnduinOS 包服务器",
                "label_key": "field.apkg_server",
                "type": "combo",
                "options": APKG_SERVERS,
                "help": "AnduinOS 叠加包的 APT 服务器地址。",
                "help_key": "help.apkg_server",
            },
            {
                "key": "APKG_CERT_NAME",
                "label": "签名证书名称",
                "label_key": "field.cert_name",
                "type": "text",
                "help": "从 APKG 服务器下载并验证仓库所用的 GPG 证书名称。",
                "help_key": "help.cert_name",
            },
            {
                "key": "APT_CONFIG_PACKAGE",
                "label": "APT 配置包",
                "label_key": "field.apt_config",
                "type": "combo",
                "options": APT_CONFIG_PACKAGES,
                "help": "用于配置 AnduinOS APT 源的配置包名（生产版 / 开发版）。",
                "help_key": "help.apt_config",
            },
        ],
    },
    {
        "id": "build",
        "label": "构建选项",
        "label_key": "section.build",
        "items": [
            {
                "key": "TARGET_ARCH",
                "label": "目标架构",
                "label_key": "field.arch",
                "type": "combo",
                "options": ARCHES,
                "help": "生成的 ISO 架构：amd64（Intel/AMD 64 位）或 arm64（ARM 64 位）。",
                "help_key": "help.arch",
            },
        ],
    },
    {
        "id": "cache",
        "label": "下载与缓存",
        "label_key": "section.cache",
        "items": [
            {
                "key": "KEEP_DOWNLOADED_DEBS",
                "label": "保留已下载的 .deb 包",
                "label_key": "field.keep_debs",
                "type": "bool",
                "help": (
                    "强烈建议开启。开启后，构建过程中 apt 下载的 .deb 包会持久保存在"
                    "工程目录的 .cache/apt-archives/ 中；当网络不稳定需要重新构建时，"
                    "可直接复用已下载的包，避免重复下载。该目录不会进入最终 ISO。"
                ),
                "help_key": "help.keep_debs",
            },
        ],
    },
    {
        "id": "lang",
        "label": "语言与区域",
        "label_key": "section.lang",
        "items": [
            {
                "key": "LANG_PACK_CODES",
                "label": "语言包代码",
                "label_key": "field.lang_packs",
                "type": "text",
                "help": "以空格分隔的语言包代码列表，构建时会自动展开为对应的 language-pack 包。",
                "help_key": "help.lang_packs",
            },
            {
                "key": "SUPPORTED_LIVE_REGIONS",
                "label": "Live 区域策略",
                "label_key": "field.regions",
                "type": "textblock",
                "help": (
                    "Live 启动菜单的区域条目，每行格式为：locale|标签|时区|XKB 布局。"
                    "必须保持 29 条，构建脚本会校验数量。"
                ),
                "help_key": "help.regions",
            },
        ],
    },
    {
        "id": "env",
        "label": "构建环境",
        "label_key": "section.env",
        "items": [
            {
                "key": "DEBIAN_FRONTEND",
                "label": "DEBIAN_FRONTEND",
                "type": "text",
                "help": "非交互式包安装模式，通常保持 noninteractive。",
                "help_key": "help.debian_frontend",
            },
            {
                "key": "LC_ALL",
                "label": "LC_ALL",
                "type": "text",
                "help": "构建进程的区域设置，强制为英文，与 Live 系统中用户可选语言无关。",
                "help_key": "help.lc_all",
            },
            {
                "key": "LANG",
                "label": "LANG",
                "type": "text",
                "help": "构建进程的语言设置。",
                "help_key": "help.lang",
            },
            {
                "key": "LANGUAGE",
                "label": "LANGUAGE",
                "type": "text",
                "help": "构建进程的语言优先级列表。",
                "help_key": "help.language",
            },
        ],
    },
]


ALL_KEYS = [item["key"] for section in SECTIONS for item in section["items"]]


def bool_from_value(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def bool_to_value(enabled: bool) -> str:
    return "true" if enabled else "false"
