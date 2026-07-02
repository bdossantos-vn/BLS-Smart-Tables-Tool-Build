"""Regression checks for shared multiselect cleanup."""

from __future__ import annotations

import unittest

from app.components.multiselect import (
    reconcile_multiselect_values,
    selected_multiselect_labels,
    valid_multiselect_values,
    widget_key_token,
)


class MultiselectHelperTest(unittest.TestCase):
    def test_valid_values_remove_blank_stale_and_duplicate_choices(self) -> None:
        self.assertEqual(
            valid_multiselect_values(["", "Control", "Missing", "Control"], ["Control", "Test"]),
            ["Control"],
        )

    def test_reconcile_can_restore_default_when_state_is_only_invalid(self) -> None:
        self.assertEqual(
            reconcile_multiselect_values(
                ["", "Missing"],
                ["Control", "Test"],
                ["Control"],
                reset_invalid_to_default=True,
            ),
            ["Control"],
        )

    def test_reconcile_preserves_intentional_empty_selection(self) -> None:
        self.assertEqual(
            reconcile_multiselect_values(
                [],
                ["Control", "Test"],
                ["Control"],
                reset_invalid_to_default=True,
            ),
            [],
        )

    def test_widget_key_token_is_stable_for_variable_names(self) -> None:
        self.assertEqual(widget_key_token("QID 12 / CELL"), "QID_12_CELL")
        self.assertEqual(widget_key_token(""), "blank")

    def test_selected_labels_use_formatter_when_available(self) -> None:
        labels = selected_multiselect_labels(
            ["2B", "3B"],
            lambda value: {
                "2B": "T2B: Definitely would buy, Probably would buy",
                "3B": "B3B: Might or might not, Probably would not, Definitely would not",
            }.get(value, value),
        )

        self.assertEqual(
            labels,
            [
                "T2B: Definitely would buy, Probably would buy",
                "B3B: Might or might not, Probably would not, Definitely would not",
            ],
        )


if __name__ == "__main__":
    unittest.main()
