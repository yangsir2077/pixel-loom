"""Local design notes must not leak into maintained source or portable guides."""
from pathlib import Path
import tempfile
import unittest

from tools.build_release import DOCS, TOP, EXTRA, documentation_files, source_files
from tools.package_windows import copy_documentation


class ReleaseSelectionTests(unittest.TestCase):
    def test_bundles_keep_formal_guides_and_tests_without_local_drafts(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'source';target=Path(folder)/'runtime'
            names=[*TOP,*EXTRA,*(f'docs/{name}' for name in DOCS),
                   'docs/LOCAL_DESIGN_PLAN.md','docs/drafts/notes.md',
                   'tests/test_formal.py','tests/__pycache__/test_formal.pyc',
                   'pixel_workbench/resources/ART_DIRECTION.md']
            for name in names:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(name,encoding='utf-8')
            selected={p.relative_to(root).as_posix() for p in source_files(root)}
            self.assertTrue({f'docs/{name}' for name in DOCS} <= selected)
            self.assertIn('tests/test_formal.py',selected)
            self.assertIn('CONTRIBUTORS.md',selected)
            self.assertIn('pixel_workbench/resources/ART_DIRECTION.md',selected)
            self.assertFalse(any('DESIGN_PLAN' in name or '/drafts/' in name or '__pycache__' in name for name in selected))
            copy_documentation(target,root)
            self.assertEqual({p.name for p in (target/'docs').iterdir()},set(DOCS))
            self.assertTrue((root/'docs/LOCAL_DESIGN_PLAN.md').exists())
            leftover=target/'docs/OLD_LOCAL_PLAN.md'
            leftover.write_text('Keep this local file; do not ship it.',encoding='utf-8')
            with self.assertRaises(ValueError):copy_documentation(target,root)
            self.assertTrue(leftover.exists())
            (root/'docs'/DOCS[0]).unlink()
            with self.assertRaises(ValueError):documentation_files(root)


if __name__=='__main__':unittest.main()
