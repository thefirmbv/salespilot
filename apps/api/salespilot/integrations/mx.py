"""MX-record based detection of the email provider for a domain.

We classify a domain into one of:
  - 'm365'   if any MX hostname ends in *.mail.protection.outlook.com
  - 'google' if any MX hostname matches *aspmx.l.google.com or googlemail.com
  - 'other'  if MX records exist but match neither
  - 'unknown' if no MX records can be resolved

This is one of the three signals feeding our callscript engine. It also
contributes to the lead score.
"""

import asyncio
import socket
from dataclasses import dataclass


@dataclass
class MxResult:
    platform: str   # m365 | google | other | unknown
    records: list[str]


def _classify(records: list[str]) -> str:
    if not records:
        return "unknown"
    joined = " ".join(records).lower()
    if "mail.protection.outlook.com" in joined or "outlook.com" in joined:
        return "m365"
    if (
        "aspmx.l.google.com" in joined
        or "googlemail.com" in joined
        or ".google.com." in joined
    ):
        return "google"
    return "other"


def _resolve_mx_sync(domain: str) -> list[str]:
    """Use stdlib only — Python doesn't ship an MX resolver, so we do a
    very small DNS query over UDP to a public resolver. To keep things
    simple we shell out to `getent` / `nslookup` if dnspython is missing.

    We try dnspython first since it's cleaner, fall back to a subprocess.
    """
    try:
        import dns.resolver  # type: ignore[import-not-found]

        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5.0
        answers = resolver.resolve(domain, "MX")
        return [str(r.exchange).rstrip(".") for r in answers]
    except Exception:  # noqa: BLE001
        pass

    # Fallback: shell out to `host` if available (Linux).
    import shutil
    import subprocess

    binary = shutil.which("host") or shutil.which("nslookup")
    if not binary:
        return []
    try:
        out = subprocess.run(
            [binary, "-t", "MX", domain] if "host" in binary else [binary, "-type=MX", domain],
            capture_output=True,
            text=True,
            timeout=5,
        )
        records: list[str] = []
        for line in out.stdout.splitlines():
            line = line.strip()
            # 'example.com mail is handled by 10 mx.example.com.'
            if " mail is handled by " in line:
                parts = line.split()
                if parts:
                    records.append(parts[-1].rstrip("."))
            elif "mail exchanger =" in line:
                parts = line.split("=", 1)
                if len(parts) == 2:
                    pieces = parts[1].split()
                    if pieces:
                        records.append(pieces[-1].rstrip("."))
        return records
    except (subprocess.TimeoutExpired, OSError):
        return []


async def detect_mail_platform(domain: str) -> MxResult:
    """Look up MX records and classify into m365/google/other/unknown.

    `domain` may include or omit the leading 'www.' — we strip it.
    """
    cleaned = (domain or "").lower().strip()
    for prefix in ("http://", "https://"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = cleaned.split("/", 1)[0]
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    if not cleaned or "." not in cleaned:
        return MxResult(platform="unknown", records=[])

    loop = asyncio.get_running_loop()
    try:
        records = await loop.run_in_executor(None, _resolve_mx_sync, cleaned)
    except Exception:  # noqa: BLE001
        records = []
    return MxResult(platform=_classify(records), records=records)


def _safe_socket_check() -> None:
    """Exists only so the file imports cleanly without dnspython at runtime;
    we use it as a no-op marker referenced elsewhere."""
    socket.gethostname()
