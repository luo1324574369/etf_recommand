import unittest
from config.settings import ETF_SECTOR_TO_SW, ETF_UNIVERSE


class TestSectorMapping(unittest.TestCase):
    """ETF sector → 申万行业映射"""

    def test_mapping_exists(self):
        self.assertIsInstance(ETF_SECTOR_TO_SW, dict)

    def test_all_etf_sectors_covered(self):
        """ETF_UNIVERSE 中所有 sector 都在映射里"""
        sectors_in_universe = {etf['sector'] for etf in ETF_UNIVERSE}
        for sector in sectors_in_universe:
            self.assertIn(sector, ETF_SECTOR_TO_SW,
                          f"sector '{sector}' 未在 ETF_SECTOR_TO_SW 中")

    def test_empty_sectors_are_explicit_empty_list(self):
        """宽基/红利/海外 应显式为空列表"""
        self.assertEqual(ETF_SECTOR_TO_SW['宽基'], [])
        self.assertEqual(ETF_SECTOR_TO_SW['红利'], [])
        self.assertEqual(ETF_SECTOR_TO_SW['海外'], [])

    def test_mapped_sectors_nonempty(self):
        """消费/医药/科技 等映射应有内容"""
        self.assertGreater(len(ETF_SECTOR_TO_SW['消费']), 0)
        self.assertGreater(len(ETF_SECTOR_TO_SW['医药']), 0)


if __name__ == '__main__':
    unittest.main()
