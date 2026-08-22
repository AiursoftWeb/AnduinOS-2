"""Command dispatch for the in-guest AT-SPI driver."""

from .accounts import *  # noqa: F403
from .applications import *  # noqa: F403
from .core import *  # noqa: F403
from .files import *  # noqa: F403
from .installer import *  # noqa: F403
from .session import *  # noqa: F403
from .shell import *  # noqa: F403


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "install",
            "secure-shell-prepare",
            "secure-shell-row",
            "secure-shell-probe",
            "secure-shell-on",
            "secure-shell-off",
            "secure-shell-assert-on",
            "secure-shell-assert-off",
            "snapshots-manager",
            "font-rendering",
            "appimage-file",
            "appimage-file-non-executable",
            "windows-executable-thumbnail",
            "windows-executable-file",
            "public-cpuz-file",
            "file-image-thumbnail",
            "file-video-thumbnail",
            "file-image-open",
            "file-video-open",
            "file-deb-software",
            "file-chinese-editor",
            "rime-input-prepare",
            "rime-input-assert",
            "snapshot-restore-arm",
            "accounts-create",
            "accounts-change-password",
            "gdm-select-user",
            "gdm-audit-users",
            "theme-set",
            "theme-assert-marker",
            "shell-initial-overview",
            "shortcut-alt-tab",
            "shortcut-super-tab",
            "shortcut-super-i",
            "settings-about-branding",
            "installed-region-zh-cn",
            "localization-zh-cn",
            "shortcut-super-u",
            "shortcut-screenshot",
            "shell-start-button",
            "shell-panel-pin",
            "shell-panel-pin-persisted",
            "shell-panel-remove",
            "shell-appindicator-roundtrip",
            "shell-desktop-icons",
            "shell-desktop-terminal",
            "shell-desktop-shortcut",
            "shell-spotify-store",
            "public-wechat-install",
            "public-wechat-tray",
            "swapcontrol-green",
        ),
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected", default="")
    parser.add_argument("--account", default="")
    parser.add_argument("--full-name", default="")
    parser.add_argument("--original-account", default="")
    parser.add_argument("--original-full-name", default="")
    parser.add_argument("--filename", default="")
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    try:
        if args.mode == "install":
            if args.config is None:
                raise UiFailure("Installer mode requires --config")
            install(json.loads(args.config.read_text(encoding="utf-8")), args.evidence)
        elif args.mode == "secure-shell-prepare":
            prepare_secure_shell(args.evidence)
        elif args.mode == "secure-shell-row":
            probe_secure_shell_row(args.evidence)
        elif args.mode == "secure-shell-probe":
            probe_secure_shell_switch(args.evidence)
        elif args.mode.startswith("secure-shell-assert-"):
            assert_secure_shell(args.mode.endswith("on"), args.evidence)
        elif args.mode.startswith("secure-shell-"):
            toggle_secure_shell(args.mode.endswith("on"), args.evidence)
        elif args.mode == "snapshots-manager":
            verify_snapshots_manager(args.evidence)
        elif args.mode == "font-rendering":
            verify_font_rendering(args.evidence)
        elif args.mode == "appimage-file":
            verify_appimage_file(args.evidence)
        elif args.mode == "appimage-file-non-executable":
            verify_non_executable_appimage_file(args.evidence)
        elif args.mode == "windows-executable-thumbnail":
            verify_windows_executable_thumbnail(args.evidence)
        elif args.mode == "windows-executable-file":
            verify_windows_executable_file(args.evidence)
        elif args.mode == "public-cpuz-file":
            verify_public_cpuz_file(args.filename, args.evidence)
        elif args.mode == "file-image-thumbnail":
            verify_file_thumbnail("AnduinOS-Image.png", args.evidence)
        elif args.mode == "file-video-thumbnail":
            verify_file_thumbnail("AnduinOS-Video.mp4", args.evidence)
        elif args.mode == "file-image-open":
            verify_image_open(args.evidence)
        elif args.mode == "file-video-open":
            verify_video_open(args.evidence)
        elif args.mode == "file-deb-software":
            verify_deb_software(args.evidence)
        elif args.mode == "file-chinese-editor":
            verify_chinese_editor(args.evidence)
        elif args.mode == "rime-input-prepare":
            prepare_rime_input(args.evidence)
        elif args.mode == "rime-input-assert":
            if not args.expected:
                raise UiFailure("Rime assertion mode requires --expected")
            assert_rime_input(args.expected, args.evidence)
        elif args.mode == "snapshot-restore-arm":
            if not args.expected:
                raise UiFailure("Snapshot restore mode requires --expected")
            arm_snapshot_restore(args.expected, args.evidence)
        elif args.mode == "accounts-create":
            if not args.account or not args.full_name:
                raise UiFailure("Account creation requires account and full name")
            create_user(args.account, args.full_name, args.evidence)
        elif args.mode == "accounts-change-password":
            change_own_password(args.evidence)
        elif args.mode == "gdm-select-user":
            if not args.account or not args.full_name:
                raise UiFailure("GDM selection requires account and full name")
            select_gdm_user(args.account, args.full_name, args.evidence)
        elif args.mode == "gdm-audit-users":
            if not all(
                (
                    args.account,
                    args.full_name,
                    args.original_account,
                    args.original_full_name,
                )
            ):
                raise UiFailure("GDM audit requires both account identities")
            audit_gdm_users(
                args.account,
                args.full_name,
                args.original_account,
                args.original_full_name,
                args.evidence,
            )
        elif args.mode == "theme-set":
            if args.expected not in {"light", "dark"}:
                raise UiFailure("Theme selection requires --expected light or dark")
            set_desktop_theme(args.expected, args.evidence)
        elif args.mode == "theme-assert-marker":
            if not args.expected:
                raise UiFailure("Theme marker assertion requires --expected")
            assert_theme_marker(args.expected, args.evidence)
        elif args.mode == "shell-initial-overview":
            assert_initial_overview_hidden(args.evidence)
        elif args.mode == "shortcut-alt-tab":
            exercise_alt_tab(args.evidence)
        elif args.mode == "shortcut-super-tab":
            exercise_super_tab(args.evidence)
        elif args.mode == "shortcut-super-i":
            exercise_super_i(args.evidence)
        elif args.mode == "settings-about-branding":
            exercise_settings_about_branding(args.evidence)
        elif args.mode == "installed-region-zh-cn":
            observe_installed_region_zh_cn(args.evidence)
        elif args.mode == "localization-zh-cn":
            exercise_localization_zh_cn(args.evidence)
        elif args.mode == "shortcut-super-u":
            exercise_super_u(args.evidence)
        elif args.mode == "shortcut-screenshot":
            exercise_screenshot_shortcut(args.evidence)
        elif args.mode == "shell-start-button":
            exercise_start_button(args.evidence)
        elif args.mode == "shell-panel-pin":
            exercise_panel_pin(args.evidence)
        elif args.mode == "shell-panel-pin-persisted":
            exercise_panel_pin_persisted(args.evidence)
        elif args.mode == "shell-panel-remove":
            exercise_panel_remove(args.evidence)
        elif args.mode == "shell-appindicator-roundtrip":
            exercise_appindicator_roundtrip(args.evidence)
        elif args.mode == "shell-desktop-icons":
            verify_default_desktop_icons(args.evidence)
        elif args.mode == "shell-desktop-terminal":
            exercise_desktop_terminal(args.evidence)
        elif args.mode == "shell-desktop-shortcut":
            exercise_desktop_shortcut(args.evidence)
        elif args.mode == "shell-spotify-store":
            exercise_spotify_store(args.evidence)
        elif args.mode == "public-wechat-install":
            exercise_wechat_install(args.evidence)
        elif args.mode == "public-wechat-tray":
            exercise_wechat_tray(args.evidence)
        elif args.mode == "swapcontrol-green":
            exercise_swapcontrol_green(args.evidence)
        else:
            raise UiFailure(f"Unhandled AT-SPI driver mode: {args.mode}")
        return 0
    except Exception as error:
        event("failure", error=str(error), type=type(error).__name__)
        try:
            dump_accessibility(args.evidence / "last-accessibility-tree.txt")
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
