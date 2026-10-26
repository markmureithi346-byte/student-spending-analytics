from __future__ import annotations

import unittest

from student_spending import components


class DisplayShareTests(unittest.TestCase):
    def test_equal_parts_add_up_to_exactly_one_hundred(self) -> None:
        shares = components.display_share_pcts([100 / 7] * 7)
        self.assertEqual(sum(shares), 100.0)
        self.assertEqual(shares.count(14.3), 6)
        self.assertEqual(shares.count(14.2), 1)

    def test_spare_tenths_go_to_the_largest_remainders(self) -> None:
        self.assertEqual(
            components.display_share_pcts([1.0, 1.0, 1.0]),
            [33.4, 33.3, 33.3],
        )

    def test_exact_fixture_shares_are_unchanged(self) -> None:
        shares = components.display_share_pcts([48.0, 36.0, 14.4, 1.6, 0.0])
        self.assertEqual(shares, [48.0, 36.0, 14.4, 1.6, 0.0])
        self.assertEqual(sum(shares), 100.0)

    def test_zero_and_negative_parts_are_safe(self) -> None:
        self.assertEqual(components.display_share_pcts([]), [])
        self.assertEqual(components.display_share_pcts([0.0, 0.0]), [0.0, 0.0])
        self.assertEqual(
            components.display_share_pcts([-10.0, 1.0, 1.0]),
            [0.0, 50.0, 50.0],
        )

    def test_whole_percent_rounding_also_adds_up(self) -> None:
        shares = components.display_share_pcts([1] * 7, decimals=0)
        self.assertEqual(sum(shares), 100.0)
        self.assertEqual(shares.count(15.0), 2)
        self.assertEqual(shares.count(14.0), 5)


if __name__ == "__main__":
    unittest.main()
