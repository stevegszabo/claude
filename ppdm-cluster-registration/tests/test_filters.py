"""Direct unit tests for the shared PPDM filter-expression builder."""
import unittest

from ppdm_cluster_registration.filters import build_filter


class BuildFilterTests(unittest.TestCase):
    def test_no_filters_returns_base_filter_unchanged(self):
        self.assertEqual(build_filter('type eq "X"'), 'type eq "X"')

    def test_no_base_filter_and_no_fields_returns_none(self):
        self.assertIsNone(build_filter(None))

    def test_combines_base_filter_with_arbitrary_fields(self):
        filt = build_filter('type eq "X"', host="10.0.0.1", id="c1")
        self.assertIn('type eq "X"', filt)
        self.assertIn('host lk "%10.0.0.1%"', filt)
        self.assertIn('id lk "%c1%"', filt)

    def test_omits_clauses_for_falsy_values(self):
        filt = build_filter(None, host="10.0.0.1", id=None)
        self.assertEqual(filt, 'host lk "%10.0.0.1%"')


if __name__ == "__main__":
    unittest.main()
