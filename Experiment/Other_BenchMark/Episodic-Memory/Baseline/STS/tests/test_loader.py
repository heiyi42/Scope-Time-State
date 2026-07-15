from __future__ import annotations

import sys
import unittest
from pathlib import Path


STS_DIR = Path(__file__).resolve().parents[1]
if str(STS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(STS_DIR.parent))

from STS.loader import load_chapters, load_qa


class LoaderTests(unittest.TestCase):
    def test_fixed_book_has_196_ordered_chapters(self):
        chapters = load_chapters()
        self.assertEqual(196, len(chapters))
        self.assertEqual(list(range(1, 197)), [row.chapter_id for row in chapters])
        self.assertTrue(all(row.text.strip() for row in chapters))

    def test_qa_loader_is_a_separate_explicit_call(self):
        rows = load_qa()
        self.assertEqual(686, len(rows))
        self.assertEqual(list(range(686)), [row.row_index for row in rows])


if __name__ == "__main__":
    unittest.main()
