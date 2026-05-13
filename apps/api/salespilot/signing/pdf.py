"""SEPA mandate PDF generator.

Renders a signed SEPA direct-debit mandate as a PDF that mirrors the
canonical IT-gemak template plus a final 'audit trail' page.

Why reportlab over weasyprint:
  * pure Python, zero system dependencies (no cairo/pango)
  * fast enough for synchronous generation inside an HTTP request
  * the layout we need is plain text + a few images, so we don't miss
    weasyprint's HTML/CSS niceties
"""

from __future__ import annotations

import base64
import io
from datetime import datetime
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


CREDITOR_NAME = "IT-gemak B.V."
CREDITOR_ADDRESS = "Broekdijk West 19U, 3621LV Breukelen"
CREDITOR_PHONE = "030 - 737 0836"
CREDITOR_ID = "NL08ZZZ860431020000"
CREDITOR_BANK_NAME = "IT-gemak B.V."
CREDITOR_IBAN = "NL53 INGB 0676 0931 40"
CREDITOR_BIC = "INGBNL2A"
ADMIN_EMAIL = "administratie@it-gemak.nl"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "MandTitle", parent=base["Title"],
            fontName="Helvetica-Bold", fontSize=18, leading=22,
            spaceAfter=8, textColor=colors.HexColor("#128ece"),
        ),
        "h2": ParagraphStyle(
            "MandH2", parent=base["Heading2"],
            fontName="Helvetica-Bold", fontSize=11, leading=14,
            spaceBefore=12, spaceAfter=4,
            textColor=colors.HexColor("#0f172a"),
        ),
        "body": ParagraphStyle(
            "MandBody", parent=base["BodyText"],
            fontName="Helvetica", fontSize=9.5, leading=13.5,
        ),
        "small": ParagraphStyle(
            "MandSmall", parent=base["BodyText"],
            fontName="Helvetica", fontSize=8, leading=11,
            textColor=colors.HexColor("#475569"),
        ),
        "mono": ParagraphStyle(
            "MandMono", parent=base["BodyText"],
            fontName="Courier", fontSize=8.5, leading=11,
        ),
    }


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    data = [[k, v] for k, v in rows]
    t = Table(data, colWidths=[55 * mm, 110 * mm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    return t


def _signature_image(b64png: str, max_width_mm: float = 70, max_height_mm: float = 30):
    """Decode the data: URL signature and return a flowable Image.

    Falls back to a placeholder paragraph when decoding fails.
    """
    try:
        if "," in b64png:
            b64png = b64png.split(",", 1)[1]
        raw = base64.b64decode(b64png)
        buf = io.BytesIO(raw)
        img = Image(buf, width=max_width_mm * mm, height=max_height_mm * mm, kind="proportional")
        return img
    except Exception:
        styles = _styles()
        return Paragraph("<i>(geen handtekening)</i>", styles["small"])


def render_mandate_pdf(*, mandate: dict[str, Any], audit: dict[str, Any]) -> bytes:
    """Produce a PDF byte-string for the given mandate + audit info.

    Expected keys in `mandate`:
        umr, debtor_name, debtor_address, debtor_postcode, debtor_city,
        debtor_country, debtor_iban, debtor_bic, debtor_email, debtor_phone,
        debtor_kvk, sign_place, signature_png_base64, signed_at (datetime)
    """
    buf = io.BytesIO()
    styles = _styles()

    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"SEPA-incassomandaat {mandate['umr']}",
        author=CREDITOR_NAME,
    )

    story: list = []

    # Title block
    story.append(Paragraph("SEPA-incassomandaat", styles["title"]))
    story.append(Paragraph(
        f"Mandaatreferentie (UMR): <b>{mandate['umr']}</b>", styles["body"],
    ))
    story.append(Spacer(1, 6))

    # Crediteur
    story.append(Paragraph("Crediteur", styles["h2"]))
    story.append(_kv_table([
        ("Naam", CREDITOR_NAME),
        ("Adres", CREDITOR_ADDRESS),
        ("Telefoon", CREDITOR_PHONE),
        ("Crediteur ID", CREDITOR_ID),
        ("Naam bankafschrift", CREDITOR_BANK_NAME),
        ("Rekeningnummer (IBAN)", CREDITOR_IBAN),
        ("BIC-code", CREDITOR_BIC),
    ]))

    # Debiteur
    story.append(Paragraph("Debiteur", styles["h2"]))
    debtor_rows: list[tuple[str, str]] = [
        ("Naam", mandate["debtor_name"]),
        ("Adres", mandate["debtor_address"]),
        ("Postcode en Plaats", f"{mandate['debtor_postcode']}  {mandate['debtor_city']}"),
        ("Land", mandate.get("debtor_country") or "Nederland"),
        ("Rekeningnummer (IBAN)", mandate["debtor_iban"]),
    ]
    if mandate.get("debtor_bic"):
        debtor_rows.append(("BIC-code", mandate["debtor_bic"]))
    debtor_rows.append(("E-mail", mandate["debtor_email"]))
    if mandate.get("debtor_phone"):
        debtor_rows.append(("Telefoon", mandate["debtor_phone"]))
    if mandate.get("debtor_kvk"):
        debtor_rows.append(("KvK-nummer", mandate["debtor_kvk"]))
    story.append(_kv_table(debtor_rows))

    # Voorwaarden
    story.append(Paragraph("Mandaatvoorwaarden", styles["h2"]))
    voorwaarden = [
        ("Toestemming",
         "Door ondertekening van dit mandaat geeft u toestemming aan IT-gemak B.V. om via "
         "Mollie bedragen van uw rekening te incasseren voor diensten, abonnementen, "
         "materialen en werkzaamheden die u afneemt van IT-gemak B.V., tot een maximaal "
         "bedrag van \u20ac10.000 per incasso. De incasso vindt plaats na de factuurdatum."),
        ("Kosten bij stornering",
         "Indien er sprake is van een stornering of een onterechte incasso, zullen de "
         "kosten van \u20ac65,- exclusief BTW aan u worden doorberekend. U kunt een "
         f"stornering of fout melden via e-mail aan {ADMIN_EMAIL}. Deze melding wordt "
         "doorgaans binnen 2 werkdagen verwerkt."),
        ("Incassoprocedure",
         "De incasso wordt in gang gezet 7 dagen na de factuurdatum. De incasso betreft "
         "variabele bedragen, afhankelijk van de afgenomen diensten, abonnementen, "
         "materialen en werkzaamheden. Het incassobedrag kan maximaal \u20ac10.000 "
         "bedragen per transactie."),
        ("Herroepingsrecht",
         "U heeft het recht om dit SEPA-incassomandaat op elk moment te herroepen door "
         f"contact op te nemen met IT-gemak B.V. via {ADMIN_EMAIL}. De herroeping geldt "
         "vanaf de eerstvolgende geplande incasso na ontvangst en verwerking van uw "
         "herroepingsverzoek."),
        ("Duur van het mandaat",
         "Dit mandaat geldt voor onbeperkte tijd, tenzij u het schriftelijk herroept. "
         "IT-gemak B.V. behoudt zich het recht voor om het mandaat te be\u00ebindigen "
         "indien de voorwaarden van het mandaat niet worden nageleefd."),
        ("Be\u00ebindiging van het mandaat",
         "Dit mandaat blijft van kracht totdat het schriftelijk wordt ingetrokken door de "
         "debiteur of door IT-gemak B.V. Het mandaat eindigt eveneens bij be\u00ebindiging "
         "van de overeenkomst tussen IT-gemak B.V. en de debiteur."),
        ("Vragen en reclamatie",
         "Voor vragen over de incasso of om een reclamatie in te dienen, kunt u contact "
         f"opnemen met IT-gemak B.V. via {ADMIN_EMAIL}. IT-gemak B.V. streeft ernaar om "
         "vragen en klachten zorgvuldig te behandelen binnen de redelijke termijn zoals "
         "vastgelegd in de algemene voorwaarden."),
        ("Toepasselijkheid algemene voorwaarden",
         "De algemene voorwaarden van IT-gemak B.V. zijn van toepassing op alle diensten "
         "en werkzaamheden uitgevoerd door IT-gemak B.V. De algemene voorwaarden van de "
         "klant worden nadrukkelijk van de hand gewezen en maken geen deel uit van de "
         "overeenkomst of de voorwaarden waaronder IT-gemak B.V. haar werkzaamheden "
         "uitvoert."),
    ]
    for idx, (title, text) in enumerate(voorwaarden, start=1):
        story.append(Paragraph(f"<b>{idx}. {title}.</b> {text}", styles["body"]))
        story.append(Spacer(1, 3))

    # Page 3: signature + audit
    story.append(PageBreak())
    story.append(Paragraph("Ondertekening", styles["h2"]))
    story.append(_kv_table([
        ("Plaats", mandate["sign_place"]),
        ("Datum", mandate["signed_at"].strftime("%d-%m-%Y %H:%M:%S %Z").strip()),
        ("Naam ondertekenaar", mandate["debtor_name"]),
    ]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Handtekening:", styles["small"]))
    story.append(_signature_image(mandate["signature_png_base64"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Door ondertekening van dit SEPA-incassomandaat stemt u in met de bovengenoemde "
        "voorwaarden, inclusief de toepasselijkheid van de algemene voorwaarden van "
        "IT-gemak B.V., en machtigt u IT-gemak B.V. om betalingen via automatische "
        "incasso uit te voeren in overeenstemming met de SEPA-richtlijnen.",
        styles["small"],
    ))

    # Audit trail
    story.append(Paragraph("Audit trail (digitale ondertekening)", styles["h2"]))
    audit_rows: list[tuple[str, str]] = [
        ("Mandaatreferentie (UMR)", mandate["umr"]),
        ("Tijdstempel server (UTC)",
         mandate["signed_at"].astimezone().strftime("%Y-%m-%d %H:%M:%S %z")),
    ]
    if audit.get("ip_address"):
        audit_rows.append(("IP-adres ondertekenaar", str(audit["ip_address"])))
    geo_parts = [str(audit[k]) for k in ("geo_city", "geo_region", "geo_country") if audit.get(k)]
    if geo_parts:
        audit_rows.append(("Geo-locatie (bij benadering)", ", ".join(geo_parts)))
    if audit.get("geo_lat") is not None and audit.get("geo_lon") is not None:
        audit_rows.append(("Coordinates", f"{audit['geo_lat']}, {audit['geo_lon']}"))
    if audit.get("user_agent"):
        ua = str(audit["user_agent"])
        audit_rows.append(("Browser / user-agent", ua[:120] + ("\u2026" if len(ua) > 120 else "")))
    if audit.get("kvk_verified") and audit.get("kvk_verified_at"):
        audit_rows.append((
            "KvK-controle uitgevoerd",
            "Ja, geverifieerd om "
            + audit["kvk_verified_at"].strftime("%Y-%m-%d %H:%M:%S %z"),
        ))
    else:
        audit_rows.append((
            "KvK-controle uitgevoerd",
            "Nee (geen geldig KvK-nummer opgegeven of niet gevonden)",
        ))
    story.append(_kv_table(audit_rows))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Dit document is digitaal vastgelegd op de servers van IT-gemak B.V. via het "
        "ondertekenportaal sign.it-gemak.nl. De SHA-256-hash van dit PDF-bestand is "
        "opgeslagen samen met bovenstaande audit-gegevens en kan op verzoek aan de bank "
        "of een toezichthouder worden overlegd om de authenticiteit van de ondertekening "
        "aan te tonen. Eventuele wijziging van dit document maakt de hash ongeldig.",
        styles["small"],
    ))

    doc.build(story)
    return buf.getvalue()
