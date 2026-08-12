import unittest
from unittest.mock import patch
from pathlib import Path

from job_finder import reporter


class NodeResolutionTests(unittest.TestCase):
    def test_find_node_executable_found(self):
        with patch('shutil.which', return_value=str(Path('node'))):
            p = reporter.find_node_executable()
            self.assertIsInstance(p, Path)

    def test_find_node_executable_missing(self):
        with patch('shutil.which', return_value=None):
            with self.assertRaises(FileNotFoundError) as cm:
                reporter.find_node_executable()
            self.assertIn('Node.js executable not found', str(cm.exception))


if __name__ == '__main__':
    unittest.main()
