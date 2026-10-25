import contextlib
import io
import os
import smtplib
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import send_ssl_report as report


class ReportTests(unittest.TestCase):
    def result(self, **changes):
        expiry = datetime.now(timezone.utc) + timedelta(days=60)
        values = dict(hostname='cdn.example.com', base_domain='example.com',
                      local_expires_at=expiry, live_expires_at=expiry, issuer='Test CA',
                      tls_version='TLSv1.3', https_ok=True, same_certificate=True, error='')
        values.update(changes)
        return report.DomainResult(**values)

    def run_report(self, results, errors=(), outcomes=None, smtp_error=None):
        env = dict(MAIL_USERNAME='sender@example.com', MAIL_PASSWORD='test-only',
                   MAIL_TO='owner@example.com', ISSUE_OUTCOME='success',
                   FILES_OUTCOME='success', UPLOAD_OUTCOME='success')
        env.update(outcomes or {})
        with patch.dict(os.environ, env, clear=True), \
             patch.object(report, 'collect_results', return_value=(results, list(errors))), \
             patch.object(report.smtplib, 'SMTP') as smtp, \
             patch.object(report.ssl, 'create_default_context'), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            client = smtp.return_value.__enter__.return_value
            if smtp_error:
                client.send_message.side_effect = smtp_error
            code = report.main()
            message = client.send_message.call_args.args[0] if client.send_message.called else None
            return code, message

    def test_verified_renewal_sends_success(self):
        code, message = self.run_report([self.result()])
        self.assertEqual(code, 0)
        self.assertIn('续期成功', message['Subject'])
        self.assertEqual(message['To'], 'owner@example.com')
        self.assertIn('cdn.example.com', message.get_body(preferencelist=('plain',)).get_content())

    def test_stale_certificate_cannot_report_success(self):
        code, message = self.run_report([self.result(same_certificate=False, error='线上证书尚未同步')])
        self.assertEqual(code, 2)
        self.assertIn('需要关注', message['Subject'])

    def test_expiring_or_unreachable_certificate_is_unhealthy(self):
        self.assertFalse(self.result(live_expires_at=datetime.now(timezone.utc) + timedelta(days=29)).healthy)
        self.assertFalse(self.result(https_ok=False).healthy)

    def test_failed_upload_cannot_report_success(self):
        code, message = self.run_report([self.result()], outcomes={'UPLOAD_OUTCOME': 'failure'})
        self.assertEqual(code, 2)
        self.assertIn('上传阿里云 CDN: failure', message.get_body(preferencelist=('plain',)).get_content())

    def test_empty_domain_configuration_is_not_success(self):
        with patch.dict(os.environ, {}, clear=True):
            results, errors = report.collect_results()
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 2)
        self.assertEqual(self.run_report(results, errors)[0], 2)

    def test_missing_mail_credentials_fail_explicitly(self):
        self.assertEqual(self.run_report([self.result()], outcomes={'MAIL_PASSWORD': ''})[0], 3)

    def test_smtp_failure_is_not_swallowed(self):
        code, _ = self.run_report([self.result()], smtp_error=smtplib.SMTPException('fixture'))
        self.assertEqual(code, 3)

    def test_html_escapes_domain_errors_and_run_link(self):
        with patch.dict(os.environ, {'RUN_URL': 'https://example.com/" onclick="bad'}, clear=True):
            body = report.build_html([self.result(hostname='<script>')], ['<img src=x>'], False)
        self.assertNotIn('<script>', body)
        self.assertNotIn('<img src=x>', body)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn('&quot;', body)

    def test_domain_match_respects_dns_boundary(self):
        self.assertEqual(report.related_base('cdn.example.com', ['example.com']), 'example.com')
        self.assertEqual(report.related_base('notexample.com', ['example.com']), '')

    def test_tls_errors_have_bounded_retries_and_safe_error(self):
        with patch.object(report.socket, 'create_connection', side_effect=OSError('private detail')) as connect, \
             patch.object(report.time, 'sleep') as sleep:
            result = report.fetch_live_certificate('cdn.example.com', attempts=2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'OSError')
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(sleep.call_count, 1)


if __name__ == '__main__':
    unittest.main()
