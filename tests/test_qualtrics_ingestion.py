"""Regression checks for standard Qualtrics dataframe ingestion."""

from __future__ import annotations

import unittest

import pandas as pd

from src.cleaning import ingest_qualtrics_dataframe
from src.metadata import build_question_metadata


class QualtricsDataframeIngestionTest(unittest.TestCase):
    def test_restored_duplicate_blacklisted_columns_are_renamed(self) -> None:
        raw_df = pd.DataFrame(
            [
                ["ResponseId", "sorter", "sorter", "cell"],
                ["Response ID", "Sorter", "Sorter duplicate", "Cell"],
                ["R_1", "1", "A", "Control"],
                ["R_2", "2", "B", "Test"],
            ]
        )

        result = ingest_qualtrics_dataframe(
            raw_df,
            source_name="survey.xlsx",
            sheet_name="Sheet1",
            blacklist=["ResponseId", "sorter"],
            whitelist_columns=["sorter"],
        )

        self.assertEqual(list(result.cleaned_df.columns), ["sorter", "sorter_2", "cell"])
        self.assertTrue(
            any("sorter -> sorter_2" in line for line in result.log_lines),
            result.log_lines,
        )

        metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )

        self.assertEqual([row["variable"] for row in metadata], ["sorter", "sorter_2", "cell"])


if __name__ == "__main__":
    unittest.main()
