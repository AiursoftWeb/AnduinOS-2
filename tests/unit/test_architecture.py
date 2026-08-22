"""Architecture contracts that keep the acceptance system small and singular."""

from support import *  # noqa: F403

import builtins
import dis
import importlib
import types
import warnings

from business.acceptance import _parser
from framework.guest_driver import GuestUiDriver


class TestSystemArchitectureTests(unittest.TestCase):
    def test_top_level_layout_exposes_only_the_six_layers_and_entrypoint(self):
        actual = {
            item.name
            for item in ROOT.iterdir()
            if item.name != "__pycache__"
        }
        self.assertEqual(
            {
                "README.md",
                "assertions",
                "business",
                "cases",
                "fixtures",
                "framework",
                "run.py",
                "unit",
            },
            actual,
        )

    def test_source_modules_and_readme_stay_reviewable(self):
        oversized = {}
        for path in ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            lines = len(path.read_text(encoding="utf-8").splitlines())
            if lines > 1800:
                oversized[str(path.relative_to(ROOT))] = lines
        self.assertEqual({}, oversized)
        self.assertLessEqual(
            len((ROOT / "README.md").read_text(encoding="utf-8").splitlines()),
            80,
        )

    def test_framework_contains_mechanisms_not_product_workflows(self):
        self.assertFalse((ROOT / "framework/runner.py").exists())
        self.assertFalse((ROOT / "framework/feature_runner.py").exists())
        self.assertTrue((ROOT / "business/install/runner.py").is_file())
        self.assertTrue((ROOT / "business/desktop/runner.py").is_file())

    def test_cli_has_no_coverage_selector_or_nonexecuting_success_mode(self):
        options = {
            option
            for action in _parser()._actions
            for option in action.option_strings
        }
        self.assertTrue({"--iso", "--arch"}.issubset(options))
        self.assertTrue(
            {
                "--profile",
                "--case",
                "--suite",
                "--smoke",
                "--list",
                "--dry-run",
                "--fail-fast",
            }.isdisjoint(options)
        )

    def test_makefile_exposes_one_complete_test_target(self):
        makefile = (ROOT.parent / "makefile").read_text(encoding="utf-8")
        targets = re.findall(r"^(test[^: ]*):", makefile, re.MULTILINE)
        self.assertEqual(["test"], targets)
        recipe = makefile[makefile.index("test:\n") :]
        self.assertIn("unittest discover", recipe)
        self.assertIn("python3 tests/run.py --iso", recipe)

    def test_default_selection_is_the_complete_architecture_inventory(self):
        matrix = TestMatrix.load(ROOT / "cases/install.json")
        registry = FeatureSuiteRegistry.load(ROOT / "cases/desktop.json", matrix)
        for architecture in Architecture:
            with self.subTest(architecture=architecture.value):
                scenarios = matrix.select(architecture, ())
                suites = registry.select(architecture)
                self.assertEqual(
                    {item.id for item in matrix.scenarios if item.supports(architecture)},
                    {item.id for item in scenarios},
                )
                self.assertEqual(
                    {item.id for item in registry.suites if item.supports(architecture)},
                    {item.id for item in suites},
                )


class GuestUiDriverPackagingTests(unittest.TestCase):
    def test_font_driver_uses_the_host_upload_location(self):
        source = (ROOT / "assertions/guest/ui/files.py").read_text(encoding="utf-8")
        self.assertIn(
            'Path(__file__).resolve().parent.parent / "font_fixture.py"',
            source,
        )
        install = _source_tree(ROOT / "business/install")
        self.assertIn('f"{remote_root}/font_fixture.py"', install)

    def test_every_guest_function_has_its_cross_module_globals(self):
        package = ROOT / "assertions/guest/ui"
        failures = {}
        for path in sorted(package.glob("*.py")):
            if path.name == "__init__.py":
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                module = importlib.import_module(f"assertions.guest.ui.{path.stem}")
            for name, function in vars(module).items():
                if not isinstance(function, types.FunctionType):
                    continue
                if function.__module__ != module.__name__:
                    continue
                missing = _missing_function_globals(
                    function.__code__,
                    vars(module),
                )
                if missing:
                    failures[f"{path.name}:{name}"] = sorted(missing)
        self.assertEqual({}, failures)

    def test_upload_deploys_the_entrypoint_and_every_ui_module(self):
        console = SimpleNamespace(run=Mock(), upload=Mock())
        driver = GuestUiDriver(ROOT / "assertions/guest")

        driver.upload(console, "/run/anduinos-acceptance")

        console.run.assert_called_once_with(
            "install -d -m 0755 /run/anduinos-acceptance/ui"
        )
        calls = console.upload.call_args_list
        self.assertEqual(
            driver.entry_point,
            calls[0].args[0],
        )
        self.assertEqual(0o755, calls[0].args[2])
        uploaded_modules = {call.args[0].name for call in calls[1:]}
        expected_modules = {
            path.name for path in (driver.source / "ui").glob("*.py")
        }
        self.assertEqual(expected_modules, uploaded_modules)
        self.assertTrue(all(call.args[2] == 0o644 for call in calls[1:]))


def _missing_function_globals(code, namespace):
    missing = {
        instruction.argval
        for instruction in dis.get_instructions(code)
        if instruction.opname == "LOAD_GLOBAL"
        and instruction.argval not in namespace
        and not hasattr(builtins, instruction.argval)
    }
    for constant in code.co_consts:
        if isinstance(constant, types.CodeType):
            missing.update(_missing_function_globals(constant, namespace))
    return missing
