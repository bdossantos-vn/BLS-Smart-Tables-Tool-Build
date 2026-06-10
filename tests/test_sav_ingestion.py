"""Regression checks for SPSS SAV intake metadata."""

from __future__ import annotations

from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

import pandas as pd

from src.cleaning import ingest_qualtrics_sav
from src.metadata import build_question_metadata


class _UploadedFile:
    name = "survey.sav"

    def getvalue(self) -> bytes:
        return b"fake sav bytes"


class SavIngestionTest(unittest.TestCase):
    def test_sav_value_labels_seed_unobserved_answer_choices(self) -> None:
        dataframe = pd.DataFrame(
            {
                "ResponseId": ["R_1", "R_2"],
                "Feature Awareness": ["Search", "Images"],
                "cell": ["Control", "Test"],
            }
        )
        metadata = SimpleNamespace(
            column_names=["ResponseId", "Feature Awareness", "cell"],
            column_labels=[
                "Response ID",
                "Before today, which features were you aware of?",
                "Cell",
            ],
            variable_value_labels={
                "Feature Awareness": {
                    1: "Search",
                    2: "Images",
                    3: "Voice",
                },
                "cell": {
                    1: "Control",
                    2: "Test",
                },
            },
        )

        def fake_read_sav(path: str, **kwargs: object) -> tuple[pd.DataFrame, SimpleNamespace]:
            self.assertTrue(path.endswith(".sav"))
            self.assertTrue(kwargs["apply_value_formats"])
            return dataframe, metadata

        fake_pyreadstat = SimpleNamespace(read_sav=fake_read_sav)
        with patch.dict(sys.modules, {"pyreadstat": fake_pyreadstat}):
            result = ingest_qualtrics_sav(_UploadedFile())

        self.assertEqual(list(result.cleaned_df.columns), ["Feature Awareness", "cell"])
        self.assertEqual(
            result.question_labels["Feature Awareness"],
            "Before today, which features were you aware of?",
        )
        self.assertEqual(result.source_answer_choices["Feature Awareness"], ["Search", "Images", "Voice"])

        question_metadata = build_question_metadata(
            result.cleaned_df,
            result.question_labels,
            result.cell_column,
            result.source_answer_choices,
        )
        feature_row = next(row for row in question_metadata if row["variable"] == "Feature Awareness")
        self.assertEqual(feature_row["answer_choices_list"], ["Search", "Images", "Voice"])


if __name__ == "__main__":
    unittest.main()
