"""GROBID client for turning PDF bytes into structured TEI-XML sections.

GROBID is an optional, network-dependent service; every method here degrades
gracefully (an unreachable server or malformed response yields ``False`` / ``[]``
rather than crashing a run). TEI is parsed with ``lxml`` when available and falls
back to the stdlib ``xml.etree.ElementTree`` so no heavy dependency is required.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..http import HttpClient
from ..models import Section

TEI_NS = "http://www.tei-c.org/ns/1.0"


class GrobidClient:
    """Minimal client for a GROBID ``processFulltextDocument`` endpoint."""

    def __init__(self, url: str, http: HttpClient) -> None:
        self.url = url.rstrip("/")
        self.http = http

    def is_available(self) -> bool:
        """Return True iff the GROBID server answers ``/api/isalive``."""
        try:
            resp = self.http.get(f"{self.url}/api/isalive")
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def process_pdf(self, pdf_bytes: bytes) -> list[Section]:
        """POST ``pdf_bytes`` to GROBID and parse the TEI response to sections.

        Any failure (network, non-2xx, unparseable XML) returns ``[]`` so the
        caller can fall through to another full-text strategy.
        """
        try:
            files = {"input": ("paper.pdf", pdf_bytes, "application/pdf")}
            resp = self.http.post(
                f"{self.url}/api/processFulltextDocument",
                files=files,
                data={"consolidateHeader": "0", "consolidateCitations": "0"},
            )
            resp.raise_for_status()
            return _parse_tei(resp.text)
        except Exception:
            return []


# --------------------------------------------------------------------------- #
# TEI parsing (lazy lxml, fallback xml.etree)
# --------------------------------------------------------------------------- #
def _local_name(tag: object) -> str:
    """Namespace-stripped element name; '' for comments/PIs (non-str tags)."""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _xml_root(xml_text: str):
    """Parse ``xml_text`` into an element tree root, or None on failure."""
    if not xml_text:
        return None
    # Prefer lxml (lenient recovery parser) when it is importable.
    try:  # pragma: no cover - exercised only when lxml is installed
        from lxml import etree as LET

        data = xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text
        parser = LET.XMLParser(recover=True, resolve_entities=False)
        root = LET.fromstring(data, parser=parser)
        if root is not None:
            return root
    except Exception:
        pass
    try:
        import xml.etree.ElementTree as ET

        return ET.fromstring(xml_text)
    except Exception:
        return None


def _iter_local(root, name: str) -> Iterator:
    """Yield every descendant element whose local (unqualified) name == name."""
    for el in root.iter():
        if _local_name(getattr(el, "tag", None)) == name:
            yield el


def _text_of(el) -> str:
    """Collapse all descendant text of ``el`` into a single whitespace-run."""
    try:
        parts = [t for t in el.itertext()]
    except Exception:
        parts = [el.text or ""]
    return " ".join("".join(parts).split())


def _parse_tei(xml_text: str) -> list[Section]:
    """Extract (head, paragraphs) sections from a GROBID TEI body."""
    root = _xml_root(xml_text)
    if root is None:
        return []
    sections: list[Section] = []
    for div in _iter_local(root, "div"):
        head: str | None = None
        paras: list[str] = []
        for child in list(div):
            ln = _local_name(getattr(child, "tag", None))
            if ln == "head" and head is None:
                head = _text_of(child)
            elif ln == "p":
                txt = _text_of(child)
                if txt:
                    paras.append(txt)
        title = (head or "").strip()
        text = "\n".join(paras).strip()
        if title or text:
            sections.append(Section(title=title, text=text))
    return sections
