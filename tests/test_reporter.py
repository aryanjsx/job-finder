import unittest
import tempfile
from pathlib import Path
from openpyxl import load_workbook

from job_finder import reporter
from tests.fixtures.report_rows import load_fixture


class ReporterTests(unittest.TestCase):
    def test_generate_report_creates_xlsx_and_hyperlinks(self):
        rows = load_fixture()
        with tempfile.TemporaryDirectory() as td:
            outdir = Path(td)
            output = reporter.generate_report(rows, outdir)
            self.assertTrue(output.exists())
            wb = load_workbook(output)
            # Check that a sheet exists and that hyperlink cells contain hyperlinks
            sheet = wb['Top Matches']
            # Find first data row (row 4), original_url at column Z (26), application_url at AA (27)
            orig_cell = sheet.cell(row=4, column=26)
            app_cell = sheet.cell(row=4, column=27)
            self.assertTrue(orig_cell.hyperlink is not None)
            self.assertTrue(app_cell.hyperlink is not None)


if __name__ == '__main__':
    unittest.main()
