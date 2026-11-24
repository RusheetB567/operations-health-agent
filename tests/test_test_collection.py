"""Prevent duplicate test methods from silently hiding regression cases."""
import ast
import unittest
from pathlib import Path


class TestCollectionTests(unittest.TestCase):

    def test_no_duplicate_top_level_test_classes(self):
        duplicates = []
        for path in Path(__file__).parent.glob("test_*.py"):
            names = set()
            for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
                if isinstance(node, ast.ClassDef):
                    if node.name in names:
                        duplicates.append(f"{path.name}:{node.name}")
                    names.add(node.name)
        self.assertEqual(duplicates, [], "duplicate classes hide tests")

    def test_no_duplicate_test_method_names(self):
        duplicates = []
        for path in Path(__file__).parent.glob("test_*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                names = set()
                for method in node.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith("test_"):
                        if method.name in names:
                            duplicates.append(f"{path.name}:{node.name}.{method.name}")
                        names.add(method.name)
        self.assertEqual(duplicates, [], "duplicate methods hide tests")
