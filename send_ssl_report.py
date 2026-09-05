#!/usr/bin/env python3
"""Build and send a compact SSL renewal report email."""

from __future__ import annotations

import html
import os
import smtplib
import socket
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")


def csv_values(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def normalize_serial(value: str | None) -> str:
    return "".join(character for character in (value or "").upper() if character.isalnum())


def issuer_name(certificate: dict) -> str:
    parts = {}
    for group in certificate.get("issuer", ()):  # ((('commonName', 'R12'),), ...)
        for key, value in group:
            parts[key] = value
    return parts.get("organizationName") or parts.get("commonName") or "未知"


def parse_certificate(path: Path) -> dict:
    certificate = ssl._ssl._test_decode_cert(str(path))
    expires_at = datetime.fromtimestamp(
        ssl.cert_time_to_seconds(certificate["notAfter"]), timezone.utc
    )
    issued_at = datetime.fromtimestamp(
        ssl.cert_time_to_seconds(certificate["notBefore"]), timezone.utc
    )
    return {
        "issued_at": issued_at,
        "expires_at": expires_at,
        "serial": normalize_serial(certificate.get("serialNumber")),
        "issuer": issuer_name(certificate),
    }


def fetch_live_certificate(
    hostname: str, expected_serial: str = "", attempts: int = 12
) -> dict:
    last_error = "UNKNOWN"
    for attempt in range(attempts):
        try:
            context = ssl.create_default_context()
            with socket.create_connection((hostname, 443), timeout=10) as sock:
                with context.wrap_socket(sock, server_hostname=hostname) as tls_sock:
                    certificate = tls_sock.getpeercert()
                    expires_at = datetime.fromtimestamp(
                        ssl.cert_time_to_seconds(certificate["notAfter"]), timezone.utc
                    )
                    result = {
                        "ok": True,
                        "expires_at": expires_at,
                        "serial": normalize_serial(certificate.get("serialNumber")),
                        "issuer": issuer_name(certificate),
                        "tls_version": tls_sock.version() or "未知",
                        "error": "",
                    }
                    if (
                        expected_serial
                        and result["serial"] != expected_serial
                        and attempt + 1 < attempts
                    ):
                        time.sleep(10)
                        continue
                    return result
        except (OSError, ssl.SSLError, ValueError, KeyError) as error:
            last_error = type(error).__name__
            if attempt + 1 < attempts:
                time.sleep(10)
    return {
        "ok": False,
        "expires_at": None,
        "serial": "",
        "issuer": "未知",
        "tls_version": "未知",
        "error": last_error,
    }


def related_base(hostname: str, base_domains: Iterable[str]) -> str:
    return next(
        (domain for domain in base_domains if hostname == domain or hostname.endswith(f".{domain}")),
        "",
    )


@dataclass
class DomainResult:
    hostname: str
    base_domain: str
    local_expires_at: datetime | None
    live_expires_at: datetime | None
    issuer: str
    tls_version: str
    https_ok: bool
    same_certificate: bool
    error: str

    @property
    def days_remaining(self) -> int | None:
        if not self.live_expires_at:
            return None
        return max(0, int((self.live_expires_at - datetime.now(timezone.utc)).total_seconds() // 86400))

    @property
    def healthy(self) -> bool:
        return self.https_ok and self.same_certificate and (self.days_remaining or 0) >= 30


def collect_results() -> tuple[list[DomainResult], list[str]]:
    base_domains = csv_values("DOMAINS")
    cdn_domains = csv_values("ALIYUN_CDN_DOMAINS")
    cert_root = Path(os.getenv("CERT_ROOT", "/home/runner/certs"))
    local_certificates: dict[str, dict] = {}
    errors: list[str] = []

    for domain in base_domains:
        cert_path = cert_root / domain / "fullchain.pem"
        try:
            local_certificates[domain] = parse_certificate(cert_path)
        except (OSError, ssl.SSLError, ValueError, KeyError):
            errors.append(f"{domain}: 本地证书不可读")

    results: list[DomainResult] = []
    for hostname in cdn_domains:
        base_domain = related_base(hostname, base_domains)
        local = local_certificates.get(base_domain, {})
        live = fetch_live_certificate(hostname, local.get("serial", ""))
        same_certificate = bool(
            local.get("serial")
            and live.get("serial")
            and local["serial"] == live["serial"]
        )
        error = live.get("error", "")
        if not base_domain:
            error = "未匹配证书域名"
        elif not local:
            error = "本地证书不可读"
        elif live.get("ok") and not same_certificate:
            error = "线上证书尚未同步"

        item = DomainResult(
            hostname=hostname,
            base_domain=base_domain or "未匹配",
            local_expires_at=local.get("expires_at"),
            live_expires_at=live.get("expires_at"),
            issuer=live.get("issuer", "未知"),
            tls_version=live.get("tls_version", "未知"),
            https_ok=bool(live.get("ok")),
            same_certificate=same_certificate,
            error=error,
        )
        if item.https_ok and item.same_certificate and (item.days_remaining or 0) < 30:
            item.error = "线上证书剩余不足 30 天"
        results.append(item)

    if not base_domains:
        errors.append("未配置证书域名")
    if not cdn_domains:
        errors.append("未配置 CDN 域名")
    return results, errors


def outcome(name: str) -> str:
    value = os.getenv(name, "unknown").lower()
    return value if value in {"success", "failure", "cancelled", "skipped"} else "unknown"


def format_time(value: datetime | None) -> str:
    return value.astimezone(SHANGHAI).strftime("%Y-%m-%d") if value else "—"


def build_plain(results: list[DomainResult], errors: list[str], success: bool) -> str:
    status = "续期并验证成功" if success else "续期或验证异常"
    lines = [
        f"SSL 证书任务：{status}",
        f"执行时间：{datetime.now(SHANGHAI):%Y-%m-%d %H:%M:%S}（Asia/Shanghai）",
        "",
        "域名 / HTTPS / 线上到期日 / 剩余天数 / 与新证书一致",
    ]
    for item in results:
        lines.append(
            f"{item.hostname} / {'正常' if item.https_ok else '异常'} / "
            f"{format_time(item.live_expires_at)} / "
            f"{item.days_remaining if item.days_remaining is not None else '—'} / "
            f"{'是' if item.same_certificate else '否'}"
        )
    if errors or any(item.error for item in results):
        lines.extend(["", "异常："])
        lines.extend(f"- {message}" for message in errors)
        lines.extend(f"- {item.hostname}: {item.error}" for item in results if item.error)
    run_url = os.getenv("RUN_URL", "")
    if run_url:
        lines.extend(["", f"查看执行详情：{run_url}"])
    return "\n".join(lines)


def build_html(results: list[DomainResult], errors: list[str], success: bool) -> str:
    healthy_count = sum(item.healthy for item in results)
    days = [item.days_remaining for item in results if item.days_remaining is not None]
    shortest_days = min(days) if days else None
    status_text = "续期成功" if success else "需要关注"
    status_color = "#168267" if success else "#c2415d"
    status_background = "#e9fbf6" if success else "#fff0f4"

    rows = []
    for item in results:
        row_status = "正常" if item.healthy else "异常"
        row_color = "#168267" if item.healthy else "#c2415d"
        days_text = str(item.days_remaining) if item.days_remaining is not None else "—"
        rows.append(
            "<tr>"
            f'<td style="padding:11px 8px;border-bottom:1px solid #edf0f3;font-weight:700;word-break:break-all;">{html.escape(item.hostname)}</td>'
            f'<td style="padding:11px 6px;border-bottom:1px solid #edf0f3;color:{row_color};font-weight:700;">{row_status}</td>'
            f'<td style="padding:11px 6px;border-bottom:1px solid #edf0f3;">{format_time(item.live_expires_at)}</td>'
            f'<td align="right" style="padding:11px 6px;border-bottom:1px solid #edf0f3;">{days_text}</td>'
            f'<td style="padding:11px 8px;border-bottom:1px solid #edf0f3;">{'已同步' if item.same_certificate else '未同步'}</td>'
            "</tr>"
        )

    issue_messages = errors + [f"{item.hostname}: {item.error}" for item in results if item.error]
    issues_html = "".join(f"<li>{html.escape(message)}</li>" for message in issue_messages)
    issues_block = (
        f'<div style="margin-top:16px;padding:14px;background:#fff0f4;border-radius:12px;color:#8f304b;">'
        f'<b>异常说明</b><ul style="margin:8px 0 0;padding-left:20px;">{issues_html}</ul></div>'
        if issue_messages
        else '<div style="margin-top:16px;padding:14px;background:#f7f8fa;border-radius:12px;color:#596075;">证书申请、阿里云 CDN 上传和公网 HTTPS 验证均通过。</div>'
    )
    run_url = html.escape(os.getenv("RUN_URL", ""), quote=True)
    run_button = (
        f'<a href="{run_url}" style="display:inline-block;margin-top:16px;background:#20243a;color:#ffffff;text-decoration:none;padding:11px 16px;border-radius:10px;font-weight:700;">查看执行详情</a>'
        if run_url
        else ""
    )

    return f"""<!doctype html>
<html lang="zh-CN"><body style="margin:0;padding:0;background:#f4f5f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',Arial,sans-serif;color:#202333;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f5f8;padding:20px 8px;"><tr><td align="center">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:680px;background:#ffffff;border-radius:18px;overflow:hidden;">
<tr><td style="background:#20243a;padding:24px;color:#ffffff;"><div style="font-size:13px;color:#ffce3a;font-weight:700;letter-spacing:1px;">SSL · 自动续期</div><div style="font-size:26px;font-weight:800;margin-top:6px;">{status_text}</div><div style="font-size:13px;color:#c8cbe0;margin-top:8px;">{datetime.now(SHANGHAI):%Y-%m-%d %H:%M} · GitHub Actions</div></td></tr>
<tr><td style="padding:16px;">
<table role="presentation" width="100%" cellspacing="8" cellpadding="0"><tr>
<td width="33%" style="background:{status_background};border-radius:12px;padding:14px;"><div style="font-size:12px;color:#677080;">任务状态</div><div style="font-size:20px;font-weight:800;color:{status_color};margin-top:5px;">{status_text}</div></td>
<td width="33%" style="background:#eef0ff;border-radius:12px;padding:14px;"><div style="font-size:12px;color:#677080;">域名验证</div><div style="font-size:20px;font-weight:800;color:#5a50c8;margin-top:5px;">{healthy_count}/{len(results)}</div></td>
<td width="33%" style="background:#fff7df;border-radius:12px;padding:14px;"><div style="font-size:12px;color:#677080;">最短剩余</div><div style="font-size:20px;font-weight:800;color:#b56b00;margin-top:5px;">{shortest_days if shortest_days is not None else '—'} 天</div></td>
</tr></table>
<div style="font-size:16px;font-weight:800;margin:18px 8px 10px;">域名验证明细</div>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;font-size:12px;"><tr style="color:#73788d;background:#f7f8fa;"><th align="left" style="padding:9px 8px;">域名</th><th align="left" style="padding:9px 6px;">HTTPS</th><th align="left" style="padding:9px 6px;">线上到期</th><th align="right" style="padding:9px 6px;">剩余</th><th align="left" style="padding:9px 8px;">新证书</th></tr>{''.join(rows)}</table>
{issues_block}{run_button}
<div style="padding:16px 4px 4px;color:#9296a8;font-size:11px;line-height:1.6;">只有公网 HTTPS 可访问、证书在有效期内且线上序列号与本次新证书一致时，才标记为验证成功。</div>
</td></tr></table></td></tr></table></body></html>"""


def main() -> int:
    results, errors = collect_results()
    step_outcomes = {
        "申请证书": outcome("ISSUE_OUTCOME"),
        "校验证书文件": outcome("FILES_OUTCOME"),
        "上传阿里云 CDN": outcome("UPLOAD_OUTCOME"),
    }
    for label, value in step_outcomes.items():
        if value != "success":
            errors.append(f"{label}: {value}")

    success = bool(results) and not errors and all(item.healthy for item in results)
    plain_body = build_plain(results, errors, success)
    html_body = build_html(results, errors, success)

    if os.getenv("SSL_REPORT_OUTPUT_DIR"):
        output_dir = Path(os.environ["SSL_REPORT_OUTPUT_DIR"])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "ssl-report.txt").write_text(plain_body, encoding="utf-8")
        (output_dir / "ssl-report.html").write_text(html_body, encoding="utf-8")

    username = os.getenv("MAIL_USERNAME", "")
    password = os.getenv("MAIL_PASSWORD", "")
    recipient = os.getenv("MAIL_TO", "maqic51@gmail.com")
    if not username or not password:
        print("email_send_failed:missing_credentials", file=sys.stderr)
        return 3

    message = EmailMessage()
    message["From"] = username
    message["To"] = recipient
    message["Subject"] = f"[SSL 证书] {'✅ 续期成功' if success else '❌ 需要关注'} | {datetime.now(SHANGHAI):%Y-%m-%d}"
    message.set_content(plain_body)
    message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        print(f"email_send_failed:{type(error).__name__}", file=sys.stderr)
        return 3

    print("ssl_report_email_sent")
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
