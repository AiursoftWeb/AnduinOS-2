#!/usr/bin/python3
"""Long-lived Qt fixture for the installed appearance acceptance suite."""

from __future__ import annotations

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class ThemeFixture(QWidget):
    def __init__(self, application: QApplication) -> None:
        super().__init__()
        self._application = application
        self.setWindowTitle("AnduinOS Qt Theme Acceptance Fixture")
        self.setAccessibleName("AnduinOS Qt Theme Acceptance Fixture")
        self.setMinimumSize(900, 600)

        heading = QLabel("QT THEME FIXTURE")
        heading.setAccessibleName("QT THEME FIXTURE")
        heading_font = heading.font()
        heading_font.setPointSize(32)
        heading_font.setBold(True)
        heading.setFont(heading_font)
        self._status = QLabel()
        status_font = self._status.font()
        status_font.setPointSize(24)
        self._status.setFont(status_font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(120, 120, 120, 120)
        layout.setSpacing(40)
        layout.addStretch(1)
        layout.addWidget(heading)
        layout.addWidget(self._status)
        layout.addStretch(1)

        application.paletteChanged.connect(self.refresh)
        self.refresh()

    def refresh(self, *_args) -> None:
        palette = self._application.palette()
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        state = "DARK" if window.lightness() < 128 else "LIGHT"
        marker = (
            f"QT PALETTE {state} WINDOW {window.name()} "
            f"TEXT {text.name()}"
        )
        self._status.setText(marker)
        self._status.setAccessibleName(marker)
        print(marker, flush=True)


def main() -> int:
    application = QApplication([])
    application.setApplicationName("AnduinOS Qt Theme Acceptance Fixture")
    fixture = ThemeFixture(application)
    fixture.showMaximized()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
