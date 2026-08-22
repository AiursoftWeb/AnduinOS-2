"""Deployment of the modular AT-SPI driver into a disposable guest."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GuestUiDriver:
    source: Path

    @property
    def entry_point(self) -> Path:
        return self.source / "atspi_driver.py"

    def upload(self, console, remote_directory: str) -> None:
        """Upload the entry point and its sibling ``ui`` package."""

        package = self.source / "ui"
        modules = sorted(package.glob("*.py"))
        if not self.entry_point.is_file() or not modules:
            raise FileNotFoundError("The packaged AT-SPI guest driver is incomplete")
        console.run(f"install -d -m 0755 {remote_directory}/ui")
        console.upload(
            self.entry_point,
            f"{remote_directory}/atspi_driver.py",
            0o755,
        )
        for module in modules:
            console.upload(module, f"{remote_directory}/ui/{module.name}", 0o644)
