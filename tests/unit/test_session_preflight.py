"""Focused fail-closed checks for desktop-session readiness probes."""

from unit.support import *  # noqa: F403


class SharingServicePreflightTests(unittest.TestCase):
    HEALTHY = "\n".join(
        (
            "before_pid=1702 before_restarts=0 before_active=active",
            "()",
            "sharing-dbus=ready",
            "after_pid=1702 after_restarts=0 after_active=active",
        )
    )

    def test_accepts_one_unchanged_dbus_service(self):
        _validate_sharing_service_preflight(self.HEALTHY, 0)

    def test_rejects_restart_or_process_replacement(self):
        restarted = self.HEALTHY.replace(
            "after_pid=1702 after_restarts=0",
            "after_pid=1901 after_restarts=1",
        )
        with self.assertRaisesRegex(TestFailure, "crashed and restarted"):
            _validate_sharing_service_preflight(restarted, 0)

    def test_rejects_missing_dbus_evidence(self):
        unavailable = self.HEALTHY.replace("sharing-dbus=ready\n", "")
        with self.assertRaisesRegex(TestFailure, "omitted its health evidence"):
            _validate_sharing_service_preflight(unavailable, 0)
