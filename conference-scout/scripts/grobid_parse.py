"""GROBID-based PDF header parser.

Drop-in replacement for the pdfminer + regex approach in enrich_arxiv.parse_authors_and_affils.
Calls GROBID's /api/processHeaderDocument endpoint and parses the TEI XML response.

Why use GROBID:
- ML-based; handles unusual PDF layouts (CVF camera-ready, two-column variants) where
  the pdfminer first-page text becomes unparseable
- Natively links author → affiliation (no superscript-digit matching required)
- Extracts ORCID and emails when present
- Returns ISO 3166-1 country code directly from TEI <country> elements

Setup:
    docker run --rm -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.2

Usage:
    from grobid_parse import parse_pdf_with_grobid
    authors, affils = parse_pdf_with_grobid(pdf_bytes, "http://localhost:8070")

Returns the same (authors, affils) shape as enrich_arxiv.parse_authors_and_affils so it
slots in without downstream changes.
"""
import re
import xml.etree.ElementTree as ET
import requests

TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _findtext(elem, path):
    found = elem.find(path, TEI_NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_tei_header(tei_xml: str):
    """Parse GROBID's TEI header into (authors, affils) compatible with our schema."""
    try:
        root = ET.fromstring(tei_xml)
    except ET.ParseError:
        return [], []

    # All authors live in //teiHeader/fileDesc/sourceDesc/biblStruct/analytic/author
    author_elems = root.findall(".//tei:teiHeader//tei:sourceDesc//tei:biblStruct/tei:analytic/tei:author", TEI_NS)

    # First pass: build a canonical list of affiliations, deduped on (org_name, country)
    affil_map: dict[tuple, int] = {}     # (institution, country) → assigned index
    affils_out: list[dict] = []

    def affil_key(aff_elem):
        # Prefer <orgName type="institution">; concatenate department/laboratory if present
        parts = []
        for ot in ("laboratory", "department", "institution"):
            for org in aff_elem.findall(f"tei:orgName[@type='{ot}']", TEI_NS):
                if org.text and org.text.strip():
                    parts.append(org.text.strip())
        text = ", ".join(parts) if parts else (
            aff_elem.findtext("tei:orgName", default="", namespaces=TEI_NS).strip())
        country_elem = aff_elem.find(".//tei:country", TEI_NS)
        # GROBID uses ISO 3166-1 alpha-2 in <country key="…">
        country = (country_elem.get("key") if country_elem is not None else "") or ""
        return text, country.upper()

    def register_affil(aff_elem):
        text, country = affil_key(aff_elem)
        if not text:
            return None
        key = (text.lower(), country)
        if key in affil_map:
            return affil_map[key]
        idx = len(affils_out) + 1
        affil_map[key] = idx
        affils_out.append({"idx": idx, "text": text, "country": country})
        return idx

    # Second pass: per-author name + their affiliation indices
    authors_out: list[dict] = []
    for au in author_elems:
        pers = au.find("tei:persName", TEI_NS)
        if pers is None:
            continue
        forenames = " ".join(
            (e.text or "").strip()
            for e in pers.findall("tei:forename", TEI_NS) if e.text)
        surname = _findtext(pers, "tei:surname")
        name = f"{forenames} {surname}".strip()
        if not name or len(name.split()) < 2:
            continue

        indices = []
        for aff in au.findall("tei:affiliation", TEI_NS):
            idx = register_affil(aff)
            if idx is not None:
                indices.append(idx)

        authors_out.append({"name": name, "aff_indices": indices})

    return authors_out, affils_out


def parse_pdf_with_grobid(pdf_bytes: bytes, grobid_url: str = "http://localhost:8070",
                          timeout: int = 30) -> tuple[list, list]:
    """POST a PDF to GROBID's header endpoint; return (authors, affils)."""
    if not pdf_bytes or len(pdf_bytes) < 1000:
        return [], []
    try:
        r = requests.post(
            f"{grobid_url.rstrip('/')}/api/processHeaderDocument",
            files={"input": ("paper.pdf", pdf_bytes, "application/pdf")},
            data={"consolidateHeader": "0"},  # set to "1" to cross-check via biblio-glutton
            timeout=timeout,
        )
        if r.status_code != 200:
            return [], []
        return parse_tei_header(r.text)
    except Exception:
        return [], []


def is_grobid_alive(grobid_url: str, timeout: int = 5) -> bool:
    """Quick health probe so the pipeline can decide whether to use GROBID or fall back."""
    try:
        r = requests.get(f"{grobid_url.rstrip('/')}/api/isalive", timeout=timeout)
        return r.status_code == 200 and r.text.strip().lower() == "true"
    except Exception:
        return False


if __name__ == "__main__":
    # Smoke test: ping a local GROBID and parse a sample PDF if a URL is provided
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8070"
    alive = is_grobid_alive(url)
    print(f"GROBID at {url}: {'alive' if alive else 'not reachable'}")
    if alive and len(sys.argv) > 2:
        pdf_path = sys.argv[2]
        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()
        authors, affils = parse_pdf_with_grobid(pdf_bytes, url)
        print(f"\nAuthors ({len(authors)}):")
        for a in authors:
            print(f"  {a['name']} → aff {a['aff_indices']}")
        print(f"\nAffiliations ({len(affils)}):")
        for a in affils:
            print(f"  [{a['idx']}] ({a['country']}) {a['text']}")
