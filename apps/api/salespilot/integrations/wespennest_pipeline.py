"""Wespennest pipeline orchestrator + stub implementations.

The real Python modules (m365_scanner, msp_fingerprint, kvk_geofilter,
decision_maker_finder, overname_monitor) will be drop-in replacements
for the stub functions in here. Until those land we still want:

  * the API endpoints to be callable
  * the wn_pipeline_runs table to record what happened
  * sensible "no data" responses in the UI

Each `run_*` function returns a counters dict that is then persisted on
a WnPipelineRun row. Real scanners replace these stubs with the same
signature.

References to the planned modules (from SPEC_FINAL.md):
  - m365_scanner.py        — DNS/MX/autodiscover hints for M365 detection
  - msp_fingerprint.py     — NS/SPF/CNAME/cert SAN matching against fingerprints
  - kvk_geofilter.py       — KVK profile + PDOK geocoding + distance filter
  - decision_maker_finder.py — KVK functionarissen + email pattern + SMTP verify
  - overname_monitor.py    — RSS poll of Dutch IT news for M&A signals
"""

from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from salespilot.models.wespennest import (
    WnAcquisitionSignal,
    WnDecisionMaker,
    WnDomain,
    WnDomainSignals,
    WnKvkCompany,
    WnMsp,
    WnMspFingerprint,
    WnPipelineRun,
    WnVendorAttribution,
)


JOB_KINDS = (
    "overname_monitor",
    "domain_discovery",
    "m365_scanner",
    "msp_fingerprint",
    "kvk_geofilter",
    "decision_maker_finder",
    "email_verify",
    "full_pipeline",
)


async def _record_run(
    db: AsyncSession,
    *,
    org_id: UUID,
    job_kind: str,
    fn: Callable[[AsyncSession, UUID], Awaitable[dict[str, Any]]],
) -> WnPipelineRun:
    """Wrap a pipeline function so its execution is persisted in wn_pipeline_runs.

    The wrapped function should return a dict with keys: processed, created,
    failed, message, details. We catch exceptions so a failing job doesn't
    take down the API; it gets logged as status=failed.
    """
    started = datetime.now(UTC)
    run = WnPipelineRun(
        id=uuid4(),
        org_id=org_id,
        job_kind=job_kind,
        status="running",
        started_at=started,
        items_processed=0,
        items_created=0,
        items_failed=0,
        details={},
    )
    db.add(run)
    await db.flush()

    try:
        result = await fn(db, org_id)
        run.items_processed = int(result.get("processed", 0))
        run.items_created = int(result.get("created", 0))
        run.items_failed = int(result.get("failed", 0))
        run.message = result.get("message") or None
        run.details = result.get("details") or {}
        run.status = "success"
    except Exception as e:  # noqa: BLE001 — we want any error logged
        run.status = "failed"
        run.message = f"{type(e).__name__}: {e}"[:1000]
    finally:
        run.finished_at = datetime.now(UTC)
        await db.flush()
    return run


# ----------------------------------------------------------------------
# STUB implementations. Replace with real scanners later.
# ----------------------------------------------------------------------


async def _stub_overname_monitor(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """Reach into Dutch IT news (Computable, Dutch IT Channel, Mena, Emerce)
    via RSS and pull stories matching M&A keywords. STUB until httpx polling
    + feedparser is wired up — but we still report a sensible empty result.
    """
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": (
            "Overname-monitor staat klaar voor inschakeling. Echte RSS-poll "
            "(Computable / Dutch IT Channel / Mena / Emerce) volgt zodra de "
            "cron-worker is geactiveerd."
        ),
        "details": {
            "rss_sources": [
                "https://www.computable.nl/rss",
                "https://www.dutchitchannel.nl/feed",
                "https://www.mena.nl/feed",
                "https://www.emerce.nl/feed",
            ],
            "keywords": [
                "overname", "neemt over", "acquisitie", "acquired",
                "managed services", "msp", "investeert in",
            ],
            "stub": True,
        },
    }


async def _stub_domain_discovery(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """For each active MSP fingerprint, query crt.sh + forward seedlist to
    find customer domains. STUB."""
    msp_count = (
        await db.execute(select(WnMsp).where(WnMsp.is_active == True))  # noqa: E712
    ).scalars().all()
    return {
        "processed": len(msp_count),
        "created": 0,
        "failed": 0,
        "message": (
            f"Klaar voor {len(msp_count)} MSP's. Echte discovery via crt.sh + "
            "seedlist volgt zodra de Python-module gedeployd is."
        ),
        "details": {"stub": True, "msps_evaluated": len(msp_count)},
    }


async def _stub_m365_scanner(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """For each WnDomain in status=pending, run m365_scanner.py. STUB."""
    pending = (
        await db.execute(select(WnDomain).where(WnDomain.status == "pending"))
    ).scalars().all()
    return {
        "processed": len(pending),
        "created": 0,
        "failed": 0,
        "message": (
            f"{len(pending)} domeinen wachten op M365-scan. Stub-run; echte "
            "DNS/autodiscover/MX-detectie volgt."
        ),
        "details": {"stub": True, "pending_domains": len(pending)},
    }


async def _stub_msp_fingerprint(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """Match scanned domains against MSP fingerprints (forward mode). STUB."""
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": "Fingerprint matching staat klaar. Echte rule-engine volgt.",
        "details": {"stub": True},
    }


async def _stub_kvk_geofilter(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """KVK basisprofiel + vestiging + PDOK geocoding + 40km filter. STUB."""
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": (
            "KVK + PDOK geocoder klaar voor activatie. Heeft een KVK API-key "
            "nodig (Settings -> Integrations -> KVK)."
        ),
        "details": {"stub": True, "kvk_hq_lat": 52.1719, "kvk_hq_lon": 4.9994},
    }


async def _stub_decision_maker_finder(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """KVK Functionarissen + email pattern generator + SMTP RCPT probe. STUB."""
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": (
            "Decision-maker finder klaar. Activatie vereist KVK Functionarissen "
            "scope en uitgaande SMTP poort 25 voor RCPT probe."
        ),
        "details": {"stub": True},
    }


async def _stub_email_verify(db: AsyncSession, org_id: UUID) -> dict[str, Any]:
    """SMTP RCPT-probe of every unverified email. STUB."""
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": "E-mail verify klaar. Activatie vereist outbound SMTP.",
        "details": {"stub": True},
    }


# Real scanners live in wespennest_scanners.py. We keep the stubs above
# as backstops for jobs that have no real implementation yet (currently
# only domain_discovery and email_verify, which require seed lists +
# outbound SMTP we'll wire later).
from salespilot.integrations import wespennest_scanners as _scanners


_JOB_IMPL: dict[str, Callable[[AsyncSession, UUID], Awaitable[dict[str, Any]]]] = {
    "overname_monitor": _scanners.scan_overname_signals,
    "domain_discovery": _stub_domain_discovery,
    "m365_scanner": _scanners.scan_domain_m365,
    "msp_fingerprint": _scanners.scan_domain_msp_fingerprint,
    "kvk_geofilter": _scanners.scan_kvk_geofilter,
    "decision_maker_finder": _scanners.scan_decision_makers,
    "email_verify": _stub_email_verify,
}


async def run_pipeline_job(
    db: AsyncSession, *, org_id: UUID, job_kind: str
) -> WnPipelineRun:
    """Dispatch a single pipeline job. Used by API endpoints + cron."""
    if job_kind == "full_pipeline":
        # Run every stage end-to-end. Each stage gets its own pipeline run.
        last: WnPipelineRun | None = None
        for kind in (
            "overname_monitor",
            "domain_discovery",
            "m365_scanner",
            "msp_fingerprint",
            "kvk_geofilter",
            "decision_maker_finder",
            "email_verify",
        ):
            impl = _JOB_IMPL.get(kind)
            if impl is None:
                continue
            last = await _record_run(db, org_id=org_id, job_kind=kind, fn=impl)
        # Record an umbrella run too so the UI can show "full pipeline"
        return await _record_run(
            db,
            org_id=org_id,
            job_kind="full_pipeline",
            fn=lambda *_a, **_kw: _full_pipeline_summary(),
        )

    impl = _JOB_IMPL.get(job_kind)
    if impl is None:
        raise ValueError(f"unknown job_kind: {job_kind}")
    return await _record_run(db, org_id=org_id, job_kind=job_kind, fn=impl)


async def _full_pipeline_summary() -> dict[str, Any]:
    return {
        "processed": 0,
        "created": 0,
        "failed": 0,
        "message": "Full pipeline doorlopen — bekijk individuele job-runs voor details.",
        "details": {},
    }
