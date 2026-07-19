import unittest
import subprocess
import sys
import sqlite3
import tempfile
import os
from pathlib import Path


class TestAuditSurvivorship(unittest.TestCase):
    """生存偏差审计脚本测试"""

    def test_script_exists(self):
        """脚本文件存在"""
        script_path = Path(__file__).parent.parent / 'scripts' / 'audit_survivorship.py'
        self.assertTrue(script_path.exists())

    def test_help_message(self):
        """脚本支持 --help"""
        result = subprocess.run(
            [sys.executable, 'scripts/audit_survivorship.py', '--help'],
            capture_output=True, text=True, cwd=Path(__file__).parent.parent
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn('start', result.stdout)

    def test_clean_data_exit_zero(self):
        """干净数据（所有ETF上市早于回测起始日）→ 退出码 0"""
        # 构造临时数据库：所有ETF上市日早于 2020-01-01
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE etf_info (
                    code TEXT PRIMARY KEY,
                    name TEXT,
                    list_date TEXT
                )
            """)
            # 上市日都早于 2020-01-01
            for code in ['510300', '510500', '159915']:
                conn.execute(
                    "INSERT INTO etf_info (code, name, list_date) VALUES (?, ?, ?)",
                    (code, 'ETF', '2015-01-01')
                )
            conn.commit()
            conn.close()

            result = subprocess.run(
                [sys.executable, 'scripts/audit_survivorship.py',
                 '--start', '2020-01-01', '--db', db_path],
                capture_output=True, text=True, cwd=Path(__file__).parent.parent
            )
            self.assertEqual(result.returncode, 0)
        finally:
            os.unlink(db_path)

    def test_survivorship_bias_exit_one(self):
        """幸存者偏差数据（ETF上市晚于回测起始日）→ 退出码 1"""
        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE etf_info (
                    code TEXT PRIMARY KEY,
                    name TEXT,
                    list_date TEXT
                )
            """)
            # 510500 上市日 2021-06-01，晚于 2020-01-01
            for code, list_date in [('510300', '2015-01-01'), ('510500', '2021-06-01')]:
                conn.execute(
                    "INSERT INTO etf_info (code, name, list_date) VALUES (?, ?, ?)",
                    (code, 'ETF', list_date)
                )
            conn.commit()
            conn.close()

            result = subprocess.run(
                [sys.executable, 'scripts/audit_survivorship.py',
                 '--start', '2020-01-01', '--db', db_path],
                capture_output=True, text=True, cwd=Path(__file__).parent.parent
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn('510500', result.stdout)
        finally:
            os.unlink(db_path)


if __name__ == '__main__':
    unittest.main()
