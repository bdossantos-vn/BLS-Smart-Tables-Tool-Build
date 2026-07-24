"""Regression checks for standard Qualtrics dataframe ingestion."""

from __future__ import annotations

import unittest

import pandas as pd

from src.cleaning import ingest_qualtrics_dataframe
from src.metadata import build_question_metadata


class QualtricsDataframeIngestionTest(unittest.TestCase):
    def test_reason_checkbox_columns_collapse_to_multiselect_questions(self) -> None:
        raw_df = pd.DataFrame(
            [
                [
                    "ResponseId",
                    "Post_Negative_1",
                    "Post_Negative_4",
                    "Post_Positive_1",
                    "Post_Positive_2",
                    "cell",
                ],
                [
                    "Response ID",
                    "Negative reasons: It isn’t relevant to me",
                    "Negative reasons: The message isn’t clear",
                    "Positive reasons: It tells me what I need to know",
                    "Positive reasons: It’s visually appealing",
                    "Cell",
                ],
                ["R_1", "Selected", "Not selected", "Not selected", "Selected", "Control"],
                ["R_2", "Not selected", "Selected", "Selected", "Not selected", "Test"],
                ["R_3", "Not selected", "Not selected", "Selected", "Selected", "Test"],
            ]
        )

        result = ingest_qualtrics_dataframe(
            raw_df,
            source_name="stacked.xlsx",
            sheet_name="Sheet1",
        )

        self.assertEqual(list(result.cleaned_df.columns), ["Post_Negative", "Post_Positive", "cell"])
        self.assertEqual(
            result.cleaned_df["Post_Negative"].tolist(),
            ["It isn’t relevant to me", "The message isn’t clear", ""],
        )
        self.assertEqual(
            result.cleaned_df["Post_Positive"].tolist(),
            [
                "It’s visually appealing",
                "It tells me what I need to know",
                "It tells me what I need to know; It’s visually appealing",
            ],
        )
        self.assertEqual(result.question_labels["Post_Negative"], "Negative reasons")
        self.assertEqual(result.question_labels["Post_Positive"], "Positive reasons")
        self.assertEqual(
            result.source_answer_choices["Post_Negative"],
            ["It isn’t relevant to me", "The message isn’t clear"],
        )
        self.assertEqual(
            result.source_answer_choices["Post_Positive"],
            ["It tells me what I need to know", "It’s visually appealing"],
        )
        self.assertEqual(result.source_question_types["Post_Negative"], "Multi-Select")
        self.assertEqual(result.source_question_types["Post_Positive"], "Multi-Select")
        self.assertTrue(
            any("Collapsed 2 checkbox question group(s)" in line for line in result.log_lines),
            result.log_lines,
        )

        metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
            result.source_question_types,
        )
        type_by_variable = {
            row["variable"]: row["detected_type"]
            for row in metadata
        }
        self.assertEqual(type_by_variable["Post_Negative"], "Multi-Select")
        self.assertEqual(type_by_variable["Post_Positive"], "Multi-Select")

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
