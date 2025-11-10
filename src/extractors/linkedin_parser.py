from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from bs4 import BeautifulSoup

@dataclass
class LinkedInProfile:
    fullName: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    id: Optional[str] = None
    location: Optional[str] = None
    headline: Optional[str] = None
    profileId: Optional[str] = None
    distance: Optional[str] = None
    publicId: Optional[str] = None
    profileUrl: Optional[str] = None

    def model_dump(self) -> dict:
        return {
            "fullName": self.fullName,
            "firstName": self.firstName,
            "lastName": self.lastName,
            "id": self.id,
            "location": self.location,
            "headline": self.headline,
            "profileId": self.profileId,
            "distance": self.distance,
            "publicId": self.publicId,
            "profileUrl": self.profileUrl,
        }

_IN_URL = re.compile(r"/in/([A-Za-z0-9\-_%]+)")
_CONN_RE = re.compile(r"\b(1st|2nd|3rd|\d+(?:st|nd|rd|th))\b", re.I)

def _split_name(full: str) -> tuple[Optional[str], Optional[str]]:
    parts = [p for p in full.strip().split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[-1]

def _clean_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = " ".join(text.split())
    return t or None

def parse_people_from_html(html: str, base_url: Optional[str] = None) -> List[LinkedInProfile]:
    """
    Parse LinkedIn people search result items from HTML.

    The parser is resilient: it looks for typical patterns such as anchors with '/in/' and
    nearby text nodes for name/headline/location. It also falls back to JSON-LD person blocks.
    """
    soup = BeautifulSoup(html, "lxml")
    results: List[LinkedInProfile] = []

    # Strategy 1: cards containing anchors with '/in/' in href
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/in/" not in href:
            continue

        # Normalize profile URL (handle relative links)
        if href.startswith("//"):
            profile_url = "https:" + href
        elif href.startswith("/"):
            profile_url = "https://www.linkedin.com" + href
        else:
            profile_url = href

        # Try to infer publicId from URL
        public_id = None
        m = _IN_URL.search(href)
        if m:
            public_id = m.group(1).strip("/").split("/")[0]

        # Try to look up enclosing card container for details
        card = a
        for _ in range(4):
            if getattr(card, "parent", None) is not None:
                card = card.parent  # type: ignore[assignment]
            else:
                break

        # Candidate fields
        name_el = None
        headline_el = None
        loc_el = None
        # Search typical tags within the card
        for cand in card.find_all(["span", "div"]):
            cls = " ".join(cand.get("class", [])).lower()
            if not name_el and ("name" in cls or "actor-name" in cls or "entity-result__title-text" in cls):
                name_el = cand
            if not headline_el and ("subtitle" in cls or "headline" in cls or "entity-result__primary-subtitle" in cls):
                headline_el = cand
            if not loc_el and ("location" in cls or "entity-result__secondary-subtitle" in cls):
                loc_el = cand

        full_name = _clean_text(a.get_text()) or (name_el and _clean_text(name_el.get_text()))
        headline = headline_el and _clean_text(headline_el.get_text())
        location = loc_el and _clean_text(loc_el.get_text())

        # Guess connection distance from nearby text
        raw_text = " ".join(card.get_text(separator=" ").split())
        m_conn = _CONN_RE.search(raw_text)
        distance = m_conn.group(1) if m_conn else None

        first, last = _split_name(full_name or "")
        results.append(
            LinkedInProfile(
                fullName=full_name,
                firstName=first,
                lastName=last,
                location=location,
                headline=headline,
                publicId=public_id,
                profileUrl=profile_url,
                distance=distance,
            )
        )

    # Strategy 2: JSON-LD person objects as fallback (some pages include it)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json

            data = json.loads(script.string or "null")
        except Exception:
            continue

        def to_list(x):
            if x is None:
                return []
            return x if isinstance(x, list) else [x]

        for obj in to_list(data):
            if not isinstance(obj, dict):
                continue
            if obj.get("@type") != "Person":
                continue
            full = _clean_text(obj.get("name"))
            first, last = _split_name(full or "")
            url = obj.get("url")
            public_id = None
            if isinstance(url, str):
                m2 = _IN_URL.search(url)
                if m2:
                    public_id = m2.group(1)
            results.append(
                LinkedInProfile(
                    fullName=full,
                    firstName=first,
                    lastName=last,
                    headline=_clean_text(obj.get("jobTitle")),
                    profileUrl=url,
                    publicId=public_id,
                )
            )

    # Deduplicate by profileUrl if available, otherwise by (fullName, headline)
    uniq: dict[str, LinkedInProfile] = {}
    for r in results:
        key = r.profileUrl or f"{r.fullName}|{r.headline}"
        if key not in uniq:
            uniq[key] = r
    return list(uniq.values())