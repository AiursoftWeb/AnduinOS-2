"""Keep large GRUB framebuffer evidence off the quota-limited /tmp mount."""

from unit.support import *  # noqa: F403
from framework.grub import _GraphicalGrubMenuEditor


class GrubScratchTests(unittest.TestCase):
    def test_graphical_editor_uses_case_artifact_filesystem(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            editor = _GraphicalGrubMenuEditor(Mock(), scratch_dir=root)
            temporary = Path(editor._temporary.name)
            self.assertEqual(root, temporary.parent)
            self.assertTrue(temporary.is_dir())
            editor.close()
            self.assertFalse(temporary.exists())
