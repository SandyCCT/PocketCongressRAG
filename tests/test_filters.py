import unittest

import pandas as pd

from services.filter_utils import build_filter_options, build_multi_field_filter
from services.filters import build_final_filter


class FilterTests(unittest.TestCase):
    def test_build_filter_options_returns_sorted_unique_values(self) -> None:
        dataframe = pd.DataFrame([
            {
                "委員名字": "黃國昌",
                "所屬委員會1": "交通委員會",
                "所屬委員會2": None,
                "涵蓋層級1": "全國性",
            },
            {
                "委員名字": "王育敏",
                "所屬委員會1": "教育及文化委員會",
                "所屬委員會2": "交通委員會",
                "涵蓋層級1": "地區性",
            },
        ])

        self.assertEqual(build_filter_options(dataframe), {
            "member_names": ["王育敏", "黃國昌"],
            "committees": ["交通委員會", "教育及文化委員會"],
            "geographical_scopes": ["全國性", "地區性"],
        })

    def test_zero_fields_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            build_multi_field_filter("教育及文化委員會", 0, "所屬委員會")

    def test_one_field_returns_direct_condition(self) -> None:
        self.assertEqual(
            build_multi_field_filter("教育及文化委員會", 1, "所屬委員會"),
            {"所屬委員會1": "教育及文化委員會"},
        )

    def test_multiple_fields_return_or_condition(self) -> None:
        self.assertEqual(
            build_multi_field_filter("教育及文化委員會", 2, "所屬委員會"),
            {"$or": [
                {"所屬委員會1": "教育及文化委員會"},
                {"所屬委員會2": "教育及文化委員會"},
            ]},
        )

    def test_multiple_values_with_one_field_return_valid_or_condition(self) -> None:
        self.assertEqual(
            build_final_filter(
                {"所屬委員會": "教育及文化委員會,交通委員會"},
                {"max_committee_count": 1},
            ),
            {"$or": [
                {"所屬委員會1": "教育及文化委員會"},
                {"所屬委員會1": "交通委員會"},
            ]},
        )

    def test_one_field_combines_with_other_condition(self) -> None:
        self.assertEqual(
            build_final_filter(
                {"所屬委員會": "教育及文化委員會", "委員名字": "王小明"},
                {"max_committee_count": 1},
            ),
            {"$and": [
                {"所屬委員會1": "教育及文化委員會"},
                {"委員名字": "王小明"},
            ]},
        )


if __name__ == "__main__":
    unittest.main()
