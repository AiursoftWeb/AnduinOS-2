"""Versioned public artifacts and desktop integration identifiers."""

_SOFTWARE_SEARCH_PROVIDER_ID = "org.gnome.Software.desktop"

_CPU_Z_VERSION = "2.20.2"
_CPU_Z_ARCHIVE = f"cpu-z_{_CPU_Z_VERSION}-en.zip"
_CPU_Z_URL = f"https://download.cpuid.com/cpu-z/{_CPU_Z_ARCHIVE}"
_CPU_Z_ARCHIVE_SHA256 = (
    "320e073a6f387464ac3faac5f010b5fe70e31fab30745883d023c8372e80f3c5"
)
_CPU_Z_MEMBER = "cpuz_x64.exe"
_CPU_Z_MEMBER_SHA256 = (
    "e1b0eda853641b75fa1a890e7811bc19b3be0ece0494c60f03d34247b7650126"
)
_CPU_Z_MEMBER_SIZE = 7_428_328
_CPU_Z_MIMES = frozenset(
    {
        "application/vnd.microsoft.portable-executable",
        "application/x-msdownload",
    }
)
_CPU_Z_HANDLER = "com.anduinos.ExeRunner.desktop"

_SPOTIFY_REMOTE = "flathub"
_SPOTIFY_REMOTE_URL = "https://dl.flathub.org/repo/"
_SPOTIFY_APP_ID = "com.spotify.Client"
_SPOTIFY_ARCH = "x86_64"
_SPOTIFY_REF = f"app/{_SPOTIFY_APP_ID}/{_SPOTIFY_ARCH}/stable"

_WECHAT_APP_ID = "com.tencent.WeChat"
_WECHAT_ARCH = "x86_64"
_WECHAT_REF = f"app/{_WECHAT_APP_ID}/{_WECHAT_ARCH}/stable"


__all__ = tuple(name for name in globals() if name.startswith("_"))
