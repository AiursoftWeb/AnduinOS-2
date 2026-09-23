"""Host tablet-wheel protocol for off-screen Rescue Center controls."""

from unit.support import *  # noqa: F403


class RescueScrollTests(unittest.TestCase):
    def test_guest_scroll_request_reaches_qemu_and_is_traced(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transcript = root / "serial.log"
            trace = root / "qmp-requests.jsonl"
            transcript.touch()
            scrolled = threading.Event()

            def request_scroll(*_args, **_kwargs):
                with transcript.open("a", encoding="utf-8") as stream:
                    stream.write(
                        '{"event": "qmp-scroll", "request": "rescue-scroll-snapshots-0", '
                        '"x_px": 640, "y_px": 376, "steps": 4}\n'
                    )
                self.assertTrue(scrolled.wait(timeout=2))
                return CommandResult("", 0)

            qmp = Mock()
            qmp.scroll_pointer_pixels.side_effect = lambda *_args, **_kwargs: scrolled.set()
            vm = SimpleNamespace(
                serial=SimpleNamespace(transcript=transcript, run=request_scroll),
                qmp=qmp,
            )
            _run_with_qmp_key_requests(
                vm, "scroll-fixture", timeout=2, request_trace=trace,
            )
            qmp.scroll_pointer_pixels.assert_called_once_with(640.0, 376.0, steps=4)
            records = [json.loads(line) for line in trace.read_text().splitlines()]
            self.assertEqual(1, len(records))
            self.assertEqual("scroll", records[0]["kind"])
            self.assertIs(True, records[0]["completed"])

    @patch("framework.qmp.time.sleep")
    def test_tablet_wheel_scrolls_at_validated_screen_position(self, _sleep):
        client = QmpClient(Path("unused"))
        client.execute = Mock(return_value={})
        client.framebuffer_size = Mock(return_value=(1280, 800))
        client.scroll_pointer_pixels(640, 376, steps=2)
        calls = client.execute.call_args_list
        self.assertEqual("abs", calls[0].args[1]["events"][0]["type"])
        self.assertEqual(
            ["wheel-down", "wheel-down", "wheel-down", "wheel-down"],
            [call.args[1]["events"][0]["data"]["button"] for call in calls[1:]],
        )
        self.assertEqual(
            [True, False, True, False],
            [call.args[1]["events"][0]["data"]["down"] for call in calls[1:]],
        )
        with self.assertRaisesRegex(ProtocolError, "scroll steps"):
            client.scroll_pointer_pixels(640, 376, steps=0)
        with self.assertRaisesRegex(ProtocolError, "outside the QEMU framebuffer"):
            client.scroll_pointer_pixels(640, 819, steps=2)

    def test_tablet_wheel_request_requires_bounded_coordinates_and_steps(self):
        valid = (
            '{"event": "qmp-scroll", "request": "rescue-scroll-snapshots-0", '
            '"x_px": 640, "y_px": 376, "steps": 4}'
        )
        self.assertEqual(
            ("rescue-scroll-snapshots-0", 640.0, 376.0, 4),
            _parse_qmp_scroll_request(valid),
        )
        self.assertIsNone(_parse_qmp_scroll_request(valid.replace('"steps": 4', '"steps": 40')))
        self.assertIsNone(_parse_qmp_scroll_request(valid.replace('"x_px": 640', '"x_px": -1')))
