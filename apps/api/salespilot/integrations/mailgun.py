"""Mailgun client + signature verification for inbound webhooks.

We use Mailgun's HTTP API for sending and Mailgun's routes/webhooks for
inbound replies. Domain is on EU region by default; the base URL is
configurable.

References:
  - Mailgun HTTP API: https://documentation.mailgun.com/en/latest/api_reference.html
  - Webhook signing:  https://documentation.mailgun.com/en/latest/user_manual.html#webhooks
"""

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any

import httpx


class MailgunError(Exception):
    pass


@dataclass
class MailgunCredentials:
    base_url: str  # 'api.eu.mailgun.net' or 'api.mailgun.net'
    domain: str  # 'mail.it-gemak.nl'
    api_key: str
    webhook_signing_key: str | None = None


def _normalize_base(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u


class MailgunClient:
    def __init__(self, creds: MailgunCredentials, timeout_s: float = 20.0) -> None:
        self.creds = creds
        self.base = _normalize_base(creds.base_url)
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            auth=("api", creds.api_key),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "MailgunClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def test_connection(self) -> dict[str, Any]:
        """Ping the domain endpoint to validate creds + domain combo."""
        url = f"{self.base}/v4/domains/{self.creds.domain}"
        try:
            res = await self._client.get(url)
        except httpx.HTTPError as e:
            raise MailgunError(f"network error: {e}") from e
        if res.status_code == 401 or res.status_code == 403:
            raise MailgunError("authentication failed — wrong API key?")
        if res.status_code == 404:
            raise MailgunError(
                f"domain {self.creds.domain} not found in Mailgun (or wrong region — "
                f"using base {self.creds.base_url})"
            )
        if res.status_code >= 400:
            raise MailgunError(f"{res.status_code}: {res.text[:200]}")
        return res.json()

    async def send(
        self,
        *,
        from_full: str,  # 'Jan de Boer <jan@it-gemak.nl>'
        to: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        reply_to: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
        tags: list[str] | None = None,
        custom_vars: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Send via Mailgun's /messages endpoint.

        Returns the JSON response; the Message-Id is in the `id` field
        (Mailgun returns it without angle brackets in this format).
        """
        url = f"{self.base}/v3/{self.creds.domain}/messages"
        data: list[tuple[str, str]] = [
            ("from", from_full),
            ("to", to),
            ("subject", subject),
            ("text", body_text),
        ]
        if body_html:
            data.append(("html", body_html))
        if reply_to:
            data.append(("h:Reply-To", reply_to))
        if in_reply_to:
            data.append(("h:In-Reply-To", f"<{in_reply_to}>"))
        if references:
            data.append(("h:References", f"<{references}>"))
        # Tracking on; click-tracking off for cold mail (less spammy).
        data.append(("o:tracking", "yes"))
        data.append(("o:tracking-opens", "yes"))
        data.append(("o:tracking-clicks", "no"))
        for tag in tags or []:
            data.append(("o:tag", tag))
        for k, v in (custom_vars or {}).items():
            data.append((f"v:{k}", v))
        try:
            res = await self._client.post(url, data=data)
        except httpx.HTTPError as e:
            raise MailgunError(f"network error: {e}") from e
        if res.status_code >= 400:
            raise MailgunError(f"send failed {res.status_code}: {res.text[:300]}")
        return res.json()


def verify_webhook_signature(
    signing_key: str, timestamp: str, token: str, signature: str
) -> bool:
    """Verify a Mailgun webhook signature.

    Mailgun signs webhook payloads with HMAC-SHA256(timestamp + token).
    """
    if not signing_key or not timestamp or not token or not signature:
        return False
    mac = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=(timestamp + token).encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return hmac.compare_digest(mac.hexdigest(), signature)
