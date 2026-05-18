"""NMBRS SOAP API client voor absences (verlof) sync.

DEPRECATED: NMBRS faseert SOAP uit per 2027. Wanneer NMBRS REST een
absences-endpoint heeft -- bv. /api/employees/{id}/absences die nu nog
404 geeft -- vervangen we deze module door REST-calls in
integrations/nmbrs.py. Tot die tijd is SOAP de enige weg om verlof
uit NMBRS te halen.

Auth: WSSE-style AuthHeader in SOAP-envelope met username + token.
Geen OAuth nodig -- dit is een aparte (legacy) auth flow.

Endpoints die we gebruiken:
  DebtorService.List_GetAll                              -- alle debtors
  DebtorService.Environment_Get                          -- subdomain
  CompanyService.List_GetByDebtor                        -- companies per debtor
  EmployeeService.Absence_GetAll_AllEmployeesByCompany   -- bulk verlof per company

Bulk-fetch is veel sneller dan per-employee call (1 SOAP-roundtrip
ipv N voor N medewerkers). NMBRS rate limit is 150 calls/sec.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx


SOAP_BASE = "https://api.nmbrs.nl/soap/v3"


# XML namespaces gebruikt in responses
NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "emp": "https://api.nmbrs.nl/soap/v3/EmployeeService",
    "comp": "https://api.nmbrs.nl/soap/v3/CompanyService",
    "debt": "https://api.nmbrs.nl/soap/v3/DebtorService",
}


@dataclass
class NmbrsSoapCreds:
    """Credentials voor de SOAP-API. Username = NMBRS login email,
    token = API-token uit profiel."""
    username: str
    token: str


class NmbrsSoapError(Exception):
    """SOAP call failed (auth, server error, malformed XML)."""


def _envelope(service: str, body_xml: str, username: str, token: str) -> str:
    """Bouw een complete SOAP-envelope met AuthHeader + body.

    `service` is een van: DebtorService, CompanyService, EmployeeService.
    `body_xml` is het inner-XML van het SOAP body element (incl. method-tag).
    """
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema"
  xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Header>
    <AuthHeader xmlns="https://api.nmbrs.nl/soap/v3/{service}">
      <Username>{username}</Username>
      <Token>{token}</Token>
    </AuthHeader>
  </soap:Header>
  <soap:Body>
    {body_xml}
  </soap:Body>
</soap:Envelope>"""


async def _soap_call(
    service: str, method: str, creds: NmbrsSoapCreds,
    body_xml: str, timeout: float = 30.0,
) -> ET.Element:
    """Doe een SOAP-call. Returns het root XML element van de response."""
    envelope = _envelope(service, body_xml, creds.username, creds.token)
    url = f"{SOAP_BASE}/{service}.asmx"
    soap_action = f"https://api.nmbrs.nl/soap/v3/{service}/{method}"

    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(
            url, content=envelope,
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": soap_action,
            },
        )
    if r.status_code != 200:
        # Bij SOAP-fault zit de echte error in de body, parse die alsnog
        try:
            root = ET.fromstring(r.text)
            fault = root.find(".//soap:Fault/faultstring", NS)
            if fault is not None and fault.text:
                raise NmbrsSoapError(f"{service}.{method}: {fault.text}")
        except ET.ParseError:
            pass
        raise NmbrsSoapError(
            f"{service}.{method} HTTP {r.status_code}: {r.text[:300]}"
        )

    return ET.fromstring(r.text)


def _strip_ns(tag: str) -> str:
    """`{http://...}TagName` -> `TagName`."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _xml_to_dict(elem: ET.Element) -> Any:
    """Recursief XML -> python (dict/list/str).

    NMBRS gebruikt geen arrays als element-naam, maar herhaalde child-
    elementen met dezelfde naam. Bij meerdere kinderen met dezelfde
    naam returnen we een list, anders een dict (of string als terminaal)."""
    children = list(elem)
    if not children:
        return (elem.text or "").strip()

    # Groepeer kinderen op tag
    grouped: dict[str, list[Any]] = {}
    for child in children:
        tag = _strip_ns(child.tag)
        grouped.setdefault(tag, []).append(_xml_to_dict(child))

    # Flatten singletons
    result: dict[str, Any] = {}
    for tag, vals in grouped.items():
        result[tag] = vals[0] if len(vals) == 1 else vals
    return result


# ----- Service methods -----------------------------------------------


async def debtors_list_all(creds: NmbrsSoapCreds) -> list[dict]:
    """Alle debtors waar deze user toegang toe heeft."""
    body = '<List_GetAll xmlns="https://api.nmbrs.nl/soap/v3/DebtorService" />'
    root = await _soap_call("DebtorService", "List_GetAll", creds, body)
    result = root.find(".//debt:List_GetAllResult", NS)
    if result is None:
        return []
    data = _xml_to_dict(result)
    debtors_node = data.get("Debtor", [])
    if isinstance(debtors_node, dict):
        debtors_node = [debtors_node]
    return debtors_node


async def companies_by_debtor(
    creds: NmbrsSoapCreds, debtor_id: int,
) -> list[dict]:
    """Companies van één debtor."""
    body = f'''<List_GetByDebtor xmlns="https://api.nmbrs.nl/soap/v3/CompanyService">
  <DebtorId>{debtor_id}</DebtorId>
</List_GetByDebtor>'''
    root = await _soap_call("CompanyService", "List_GetByDebtor", creds, body)
    result = root.find(".//comp:List_GetByDebtorResult", NS)
    if result is None:
        return []
    data = _xml_to_dict(result)
    companies = data.get("Company", [])
    if isinstance(companies, dict):
        companies = [companies]
    return companies


async def absences_for_company(
    creds: NmbrsSoapCreds, company_id: int, year: int,
) -> list[dict]:
    """Alle verlof van alle medewerkers van een company in één jaar.

    Returns list van dicts met o.a.:
      EmployeeId, AbsenceId, Comment, Start, End, RegistrationStartDate,
      RegistrationEndDate, Dossier, Dossiernr, Percentage, AbsenceCause
    """
    body = f'''<Absence_GetAll_AllEmployeesByCompany xmlns="https://api.nmbrs.nl/soap/v3/EmployeeService">
  <CompanyId>{company_id}</CompanyId>
  <Year>{year}</Year>
</Absence_GetAll_AllEmployeesByCompany>'''
    root = await _soap_call(
        "EmployeeService", "Absence_GetAll_AllEmployeesByCompany",
        creds, body,
    )
    result = root.find(
        ".//emp:Absence_GetAll_AllEmployeesByCompanyResult", NS,
    )
    if result is None:
        return []
    data = _xml_to_dict(result)

    # Response struct: list van EmployeeAbsences -> EmployeeId + Absences->Absence
    # of soms direct flat. Beide normaliseren naar list van per-absence dicts.
    out: list[dict] = []

    items = data.get("EmployeeAbsences", []) or data.get("EmployeeAbsence", [])
    if isinstance(items, dict):
        items = [items]

    if items:
        for emp_abs in items:
            emp_id = emp_abs.get("EmployeeId") or emp_abs.get("Employee", {}).get("Id")
            abs_node = (
                emp_abs.get("Absences", {}).get("Absence")
                if isinstance(emp_abs.get("Absences"), dict)
                else emp_abs.get("Absences") or emp_abs.get("Absence")
            )
            if abs_node is None:
                continue
            if isinstance(abs_node, dict):
                abs_node = [abs_node]
            for a in abs_node:
                a["EmployeeId"] = emp_id
                out.append(a)
    else:
        # Soms is response direct een list van Absence-dicts met EmployeeId inline
        flat = data.get("Absence", [])
        if isinstance(flat, dict):
            flat = [flat]
        out = flat

    return out


async def fetch_all_absences(
    creds: NmbrsSoapCreds, years: list[int] | None = None,
) -> dict[int, list[dict]]:
    """Haal absences op voor alle debtors + companies in gegeven jaren.

    Returns dict mapping employee_id (int) -> list van absence-dicts.
    Default years: huidig jaar + vorig jaar.
    """
    if years is None:
        now = datetime.now()
        years = [now.year, now.year - 1]

    by_employee: dict[int, list[dict]] = {}

    debtors = await debtors_list_all(creds)
    for debtor in debtors:
        debtor_id_raw = debtor.get("Id")
        if not debtor_id_raw:
            continue
        try:
            did = int(debtor_id_raw)
        except (ValueError, TypeError):
            continue

        try:
            companies = await companies_by_debtor(creds, did)
        except NmbrsSoapError:
            continue

        for company in companies:
            cid_raw = company.get("ID") or company.get("Id")
            if not cid_raw:
                continue
            try:
                cid = int(cid_raw)
            except (ValueError, TypeError):
                continue

            for year in years:
                try:
                    rows = await absences_for_company(creds, cid, year)
                except NmbrsSoapError:
                    continue

                for a in rows:
                    emp_id = a.get("EmployeeId")
                    if not emp_id:
                        continue
                    try:
                        eid = int(emp_id)
                    except (ValueError, TypeError):
                        continue
                    a["_company_id"] = cid
                    a["_year"] = year
                    by_employee.setdefault(eid, []).append(a)

    return by_employee


# ----- Helpers voor het mappen NMBRS -> SalesPilot -------------------


def classify_absence(a: dict) -> tuple[str, str]:
    """Map NMBRS absence-data naar (code, label) voor onze opslag.

    NMBRS gebruikt 'Dossier' (= type) als integer enum:
      1 = ziek (sick)
      2 = ongeval (accident)
      4 = bevalling/zwangerschap
      5 = vakantie (vacation)
      9 = bijzonder verlof
      99 = ander
    Plus 'AbsenceCause' / 'Comment' geeft extra context.
    """
    dossier = a.get("Dossier") or a.get("Dossiernr") or ""
    cause = (a.get("AbsenceCause") or "").lower()
    comment = (a.get("Comment") or "").lower()

    dossier_str = str(dossier)
    if dossier_str == "1" or "ziek" in cause or "sick" in cause:
        return ("sick", "Ziek")
    if dossier_str == "5" or "vakantie" in cause or "vacation" in comment:
        return ("vacation", "Vakantie")
    if dossier_str == "4":
        return ("special_leave", "Zwangerschap/bevalling")
    if dossier_str == "9":
        return ("special_leave", "Bijzonder verlof")
    if "verlof" in comment or "verlof" in cause:
        return ("vacation", "Verlof")
    return ("other", f"Verlof (dossier {dossier})")


def absence_colour(code: str) -> str:
    """HaloPSA appointment colour hex per verlof-type."""
    return {
        "vacation": "#10b981",      # emerald
        "sick": "#ef4444",          # red
        "special_leave": "#f59e0b", # amber
        "other": "#6366f1",         # indigo
    }.get(code, "#6366f1")


def parse_nmbrs_date(s: str | None) -> datetime | None:
    """NMBRS SOAP date strings: '2026-05-18T00:00:00' of '2026-05-18'."""
    if not s:
        return None
    try:
        # XML datetime ISO format
        if "T" in s:
            return datetime.fromisoformat(s.split(".")[0])
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
