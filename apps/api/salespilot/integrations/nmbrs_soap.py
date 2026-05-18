"""NMBRS SOAP API client voor absences (ziekteverlof) sync.

DEPRECATED 2027: NMBRS faseert SOAP uit. Module wordt vervangen door
REST zodra absences-endpoint daar verschijnt.

Auth: NMBRS API v3 vereist AuthHeaderWithDomain met username + token +
subdomain. Subdomain ontdek je via DebtorService.Environment_Get
(retourneert `bg.nmbrs.nl` waarbij `bg` de subdomain is).

Endpoints die we gebruiken:
  DebtorService.Environment_Get                          -- subdomain ontdekken
  DebtorService.List_GetAll                              -- alle debtors
  CompanyService.List_GetByDebtor                        -- companies per debtor
  EmployeeService.Absence_GetAll_AllEmployeesByCompany   -- ziekte per jaar (bulk)

NB: NMBRS noemt het "Absence" maar dit endpoint bevat in praktijk
ALLEEN ziekte-records (Dossier=Ziekte). Vakantieverlof zit in
Leave_GetList_V2 maar bij IT-gemak blijkt dat leeg te zijn -- daar
wordt verlof niet via NMBRS geadministreerd. Voor nu sync'en we
alleen ziekte; uitbreiden naar Leave wanneer er behoefte is.

Privacy: subject in HaloPSA wordt ALTIJD generiek 'NMBRS: Afwezig'.
Geen ziekte-comment, geen percentage, geen type. AVG-medische data
hoort niet in een gedeelde agenda.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

import httpx


SOAP_BASE = "https://api.nmbrs.nl/soap/v3"

NS = {
    "soap": "http://schemas.xmlsoap.org/soap/envelope/",
    "emp": "https://api.nmbrs.nl/soap/v3/EmployeeService",
    "comp": "https://api.nmbrs.nl/soap/v3/CompanyService",
    "debt": "https://api.nmbrs.nl/soap/v3/DebtorService",
}


@dataclass
class NmbrsSoapCreds:
    """Credentials voor de SOAP-API.

    Username = NMBRS login email.
    Token = API-token uit profiel.
    Domain = subdomain ontdekt via Environment_Get (bv. 'bg').
    """
    username: str
    token: str
    domain: str = ""  # bv. 'bg' -- wordt opgehaald via Environment_Get


class NmbrsSoapError(Exception):
    """SOAP call failed (auth, server error, malformed XML)."""


def _envelope_no_domain(service: str, body_xml: str, username: str, token: str) -> str:
    """Bouw SOAP-envelope met simpele AuthHeader (zonder Domain).

    Wordt alleen gebruikt voor Environment_Get -- die heeft geen
    subdomain nodig om gevalideerd te worden.
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


def _envelope(
    service: str, body_xml: str,
    username: str, token: str, domain: str,
) -> str:
    """Bouw een complete SOAP-envelope met AuthHeaderWithDomain.

    NMBRS API v3 vereist Domain in de auth-header voor alle calls
    behalve Environment_Get. Zonder Domain -> 1001 Invalid Authentication.
    """
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
  xmlns:xsd="http://www.w3.org/2001/XMLSchema"
  xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Header>
    <AuthHeaderWithDomain xmlns="https://api.nmbrs.nl/soap/v3/{service}">
      <Username>{username}</Username>
      <Token>{token}</Token>
      <Domain>{domain}</Domain>
    </AuthHeaderWithDomain>
  </soap:Header>
  <soap:Body>
    {body_xml}
  </soap:Body>
</soap:Envelope>"""


async def _soap_call(
    service: str, method: str, creds: NmbrsSoapCreds,
    body_xml: str, timeout: float = 30.0,
    use_domain: bool = True,
) -> ET.Element:
    """Doe een SOAP-call. Returns het root XML element van de response."""
    if use_domain:
        envelope = _envelope(
            service, body_xml, creds.username, creds.token, creds.domain,
        )
    else:
        envelope = _envelope_no_domain(
            service, body_xml, creds.username, creds.token,
        )
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
        try:
            root = ET.fromstring(r.text)
            fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault/faultstring")
            if fault is not None and fault.text:
                raise NmbrsSoapError(f"{service}.{method}: {fault.text}")
        except ET.ParseError:
            pass
        raise NmbrsSoapError(
            f"{service}.{method} HTTP {r.status_code}: {r.text[:300]}"
        )

    return ET.fromstring(r.text)


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _xml_to_dict(elem: ET.Element) -> Any:
    children = list(elem)
    if not children:
        return (elem.text or "").strip()
    grouped: dict[str, list[Any]] = {}
    for child in children:
        tag = _strip_ns(child.tag)
        grouped.setdefault(tag, []).append(_xml_to_dict(child))
    result: dict[str, Any] = {}
    for tag, vals in grouped.items():
        result[tag] = vals[0] if len(vals) == 1 else vals
    return result


# ----- Service methods -----------------------------------------------


async def environment_get(creds: NmbrsSoapCreds) -> str | None:
    """Haal SubDomain op (bv. 'bg').

    Werkt zonder Domain in auth-header -- dat is juist het hele
    doel van deze call: zelf-ontdekken welk subdomain bij creds hoort.
    """
    body = '<Environment_Get xmlns="https://api.nmbrs.nl/soap/v3/DebtorService" />'
    root = await _soap_call(
        "DebtorService", "Environment_Get", creds, body, use_domain=False,
    )
    sub = root.find(".//{https://api.nmbrs.nl/soap/v3/DebtorService}SubDomain")
    if sub is not None and sub.text:
        return sub.text.strip()
    return None


async def debtors_list_all(creds: NmbrsSoapCreds) -> list[dict]:
    """Alle debtors waar deze user toegang toe heeft."""
    body = '<List_GetAll xmlns="https://api.nmbrs.nl/soap/v3/DebtorService" />'
    root = await _soap_call("DebtorService", "List_GetAll", creds, body)
    result = root.find(".//{https://api.nmbrs.nl/soap/v3/DebtorService}List_GetAllResult")
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
    body = f'''<List_GetByDebtor xmlns="https://api.nmbrs.nl/soap/v3/CompanyService">
  <DebtorId>{debtor_id}</DebtorId>
</List_GetByDebtor>'''
    root = await _soap_call("CompanyService", "List_GetByDebtor", creds, body)
    result = root.find(".//{https://api.nmbrs.nl/soap/v3/CompanyService}List_GetByDebtorResult")
    if result is None:
        return []
    data = _xml_to_dict(result)
    companies = data.get("Company", [])
    if isinstance(companies, dict):
        companies = [companies]
    return companies


async def employees_by_company(
    creds: NmbrsSoapCreds, company_id: int, employee_type: int | None = None,
) -> list[dict]:
    """Employees per company.

    employee_type filtering in NMBRS:
      2 = active payroll employees
      4 = uit dienst / inactive employees

    Voor matching met ALLE historische absences halen we standaard
    type=2 EN type=4 op en combineren we de lijsten -- inactieve
    medewerkers kunnen nog absence-records uit hun actieve periode hebben.
    """
    types_to_fetch = [employee_type] if employee_type is not None else [2, 4]
    seen_ids: set[str] = set()
    out: list[dict] = []
    for et in types_to_fetch:
        body = f'''<List_GetByCompany xmlns="https://api.nmbrs.nl/soap/v3/EmployeeService">
  <CompanyId>{company_id}</CompanyId>
  <EmployeeType>{et}</EmployeeType>
</List_GetByCompany>'''
        try:
            root = await _soap_call("EmployeeService", "List_GetByCompany", creds, body)
        except NmbrsSoapError:
            continue
        result = root.find(".//{https://api.nmbrs.nl/soap/v3/EmployeeService}List_GetByCompanyResult")
        if result is None:
            continue
        data = _xml_to_dict(result)
        emps = data.get("Employee", [])
        if isinstance(emps, dict):
            emps = [emps]
        for e in emps:
            eid = str(e.get("Id", ""))
            if eid and eid not in seen_ids:
                seen_ids.add(eid)
                out.append(e)
    return out


async def absences_for_company(
    creds: NmbrsSoapCreds, company_id: int, year: int,
) -> list[dict]:
    """Alle ziekte-records van alle medewerkers van een company in één jaar.

    Returns list van dicts met o.a.:
      AbsenceId, EmployeeId, Comment, Start, End, RegistrationStartDate,
      RegistrationEndDate, Dossier, Dossiernr, Percentage
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
        ".//{https://api.nmbrs.nl/soap/v3/EmployeeService}Absence_GetAll_AllEmployeesByCompanyResult",
    )
    if result is None:
        return []
    data = _xml_to_dict(result)
    if not isinstance(data, dict):
        return []
    items = data.get("EmployeeAbsence", [])
    if isinstance(items, dict):
        items = [items]
    return items


async def fetch_all_absences(
    creds: NmbrsSoapCreds, years: list[int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Haal absences + employee-mapping op voor alle debtors + companies.

    Returns (absences, employees) waar:
      absences = flat list van absence-records met _company_id, _year toegevoegd
      employees = flat list van {Id, Number, DisplayName, _company_id}

    NB: pakt automatisch huidige + vorig jaar als years=None.
    """
    if years is None:
        now = datetime.now()
        years = [now.year - 1, now.year]

    all_absences: list[dict] = []
    all_employees: list[dict] = []

    # Eerst subdomain regelen als die mist
    if not creds.domain:
        sub = await environment_get(creds)
        if sub:
            creds.domain = sub

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

            # Employees voor company (SOAP-ids en Number, voor matching)
            try:
                emps = await employees_by_company(creds, cid)
                for e in emps:
                    e["_company_id"] = cid
                    all_employees.extend([e])
            except NmbrsSoapError:
                pass

            # Absences per jaar
            for year in years:
                try:
                    rows = await absences_for_company(creds, cid, year)
                    for a in rows:
                        a["_company_id"] = cid
                        a["_year"] = year
                    all_absences.extend(rows)
                except NmbrsSoapError:
                    continue

    return all_absences, all_employees





async def leave_for_employee(
    creds: NmbrsSoapCreds, employee_id: int, year: int,
) -> list[dict]:
    """Verlof (vakantie) per medewerker per jaar.

    NMBRS retourneert Leave-records ZONDER unieke ID. We bouwen
    later een deterministische business-key uit (start, end, hours,
    description) zodat we toch idempotent kunnen syncen.

    Returns list met o.a. Description, Hours, UsageType, Start, End,
    StartHours, EndHours, Type, Status.
    """
    body = f'''<Leave_GetList xmlns="https://api.nmbrs.nl/soap/v3/EmployeeService">
  <EmployeeId>{employee_id}</EmployeeId>
  <Year>{year}</Year>
  <LeaveType>all</LeaveType>
  <LeaveUsageType>all</LeaveUsageType>
</Leave_GetList>'''
    try:
        root = await _soap_call("EmployeeService", "Leave_GetList", creds, body)
    except NmbrsSoapError:
        return []
    result = root.find(".//{https://api.nmbrs.nl/soap/v3/EmployeeService}Leave_GetListResult")
    if result is None:
        return []
    data = _xml_to_dict(result)
    # Lege response -> data is str (text). Geen leaves.
    if not isinstance(data, dict):
        return []
    items = data.get("Leave", [])
    if isinstance(items, dict):
        items = [items]
    return items


def leave_business_key(
    nmbrs_employee_uuid: str, start: str, end: str,
    hours: str, description: str = "",
) -> str:
    """Deterministische key voor een NMBRS Leave-record.

    NMBRS heeft geen ID voor leaves -- we bouwen een hash uit de
    velden die samen onveranderlijk zijn. Sleutel includeert de
    NMBRS REST employee-UUID (uniek over alle debtors) ipv het
    employeeNumber dat kan botsen tussen debtors.
    """
    import hashlib
    raw = f"{nmbrs_employee_uuid}|{start}|{end}|{hours}|{description}"
    h = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return f"leave_{h}"


def absence_business_key(nmbrs_absence_id: int) -> str:
    """Business-key voor NMBRS ziekteregistratie (heeft echte ID)."""
    return f"absence_{nmbrs_absence_id}"


# ----- Helpers -------------------------------------------------------


def parse_nmbrs_date(s: str | None) -> datetime | None:
    """NMBRS SOAP date strings: '2026-05-18T00:00:00' of '2026-05-18'."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        if "T" in s:
            return datetime.fromisoformat(s.split(".")[0])
        return datetime.strptime(s, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def is_fullday_absence(start: datetime, end: datetime | None) -> bool:
    """Bepaal of een absence een hele-dag-event moet zijn.

    NMBRS-records hebben altijd 00:00:00 als tijd in dit endpoint.
    Dat wijst op volledige dagen. Mocht ooit een record met een ander
    tijdstip komen (uurregistratie), zetten we 'm als specifiek
    tijdvenster ipv allday.
    """
    if start.hour != 0 or start.minute != 0:
        return False
    if end is not None and (end.hour != 0 or end.minute != 0):
        return False
    return True
