import unittest

from scanner.reconciliation import name_similarity


class NameSimilarityTests(unittest.TestCase):
    def test_initial_and_full_name(self):
        self.assertGreaterEqual(name_similarity("A. Zverev", "Alexander Zverev"), 0.9)

    def test_accents(self):
        self.assertGreaterEqual(name_similarity("João Fonseca", "Joao Fonseca"), 0.99)

    def test_wrong_first_name_is_not_safe(self):
        self.assertLess(name_similarity("Venus Williams", "Serena Williams"), 0.82)


if __name__ == "__main__":
    unittest.main()
