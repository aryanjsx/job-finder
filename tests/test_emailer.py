import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from job_finder.emailer import send_report


class EmailerTests(unittest.TestCase):
    def test_carried_over_pipeline_rows_drive_email_summary(self):
        rows = [
            {
                'company': 'Top Company',
                'title': 'Top Engineer',
                'match_score': 79,
                'recommendation': 'APPLY',
                'status': 'SEEN',
                'salary': 'Not disclosed',
                'cloud_devops_match': 'High',
            }
        ]
        rows.extend({
            'company': f'Company {index}',
            'title': f'Engineer {index}',
            'match_score': 60,
            'recommendation': 'CONSIDER / STRETCH',
            'status': 'SEEN',
            'salary': 'Not disclosed',
            'cloud_devops_match': 'Low',
        } for index in range(2, 27))
        settings = SimpleNamespace(
            email_enabled=True,
            smtp_host='smtp.example.com',
            smtp_port=587,
            smtp_username='user',
            smtp_password='password',
            email_from='from@example.com',
            email_to='to@example.com',
            smtp_use_tls=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / 'Aryan_Job_Report_2026-08-13.xlsx'
            report.write_bytes(b'workbook')
            with patch('job_finder.emailer.smtplib.SMTP') as smtp:
                server = smtp.return_value.__enter__.return_value
                self.assertTrue(send_report(settings, report, rows))
            message = server.send_message.call_args.args[0]
        body = message.get_body(preferencelist=('plain',)).get_content()
        self.assertIn('Pipeline matches: 26', body)
        self.assertIn('New matches: 0', body)
        self.assertIn('Carried-over matches: 26', body)
        self.assertIn('Recommended to apply: 1', body)
        self.assertIn('Best job: Top Engineer at Top Company', body)
        self.assertNotIn('Best job: None', body)
        self.assertIn('26 matches', message['Subject'])


if __name__ == '__main__':
    unittest.main()
