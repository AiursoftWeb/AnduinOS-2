"""Deployment of the modular AT-SPI driver into a disposable guest."""

from dataclasses import dataclass
from pathlib import Path
import shlex
import tarfile
import tempfile


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
        # Serial transfer verifies every frame and the complete archive. Bundling
        # avoids paying that round-trip cost separately for every Python module.
        remote = shlex.quote(remote_directory)
        archive_path = f"{remote_directory}/driver.tar.gz"
        with tempfile.TemporaryDirectory(prefix="anduinos-guest-driver-") as directory:
            archive = Path(directory) / "driver.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for source in (self.entry_point, *modules):
                    name = source.relative_to(self.source).as_posix()
                    info = bundle.gettarinfo(str(source), arcname=name)
                    info.mode = 0o755 if source == self.entry_point else 0o644
                    with source.open("rb") as stream:
                        bundle.addfile(info, stream)
            console.run(f"install -d -m 0755 {remote}/ui")
            try:
                console.upload(archive, archive_path, 0o644)
                console.run(
                    f"tar --no-same-owner -xzf {shlex.quote(archive_path)} -C {remote}"
                )
            finally:
                console.run(f"rm -f {shlex.quote(archive_path)}", check=False)
