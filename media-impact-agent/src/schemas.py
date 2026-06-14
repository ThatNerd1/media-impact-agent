"""schemas.py — Pydantic-Modelle für die extrahierten Daten + Plausibilitätsregeln.

Diese Schemas sind die Qualitätskontrolle: Extrahierte Daten, die hier
durchfallen, gehen in eine Review-Queue statt blind in die Datenbank.
Die Felder spiegeln das relationale DB-Schema (ad_formats, channels, price_rules).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Fachliche Grenzen, abgeleitet aus den realen Dokumenten (CPM-Preisliste,
# CTR-Werte). Werte außerhalb dieser Bereiche sind ein Warnsignal für eine
# fehlerhafte Extraktion.
CPM_MIN_EUR = 30
CPM_MAX_EUR = 120
CTR_MAX_PCT = 2.0


class BookingOption(BaseModel):
    option_name: str


class AdFormat(BaseModel):
    """Ein Anzeigenformat, z. B. 'Billboard' oder 'Dynamic Fireplace'."""
    format_key: str = Field(..., description="stabiler Schlüssel, z. B. 'dynamic_fireplace'")
    name: str
    device: Literal["stationary", "mobile", "multiscreen"]
    ctr_pct: Optional[float] = Field(None, description="durchschnittliche CTR in Prozent")
    description: Optional[str] = None
    booking_options: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    programmatic: Optional[str] = None
    required_assets: list[str] = Field(default_factory=list)
    goes_well_with: list[str] = Field(default_factory=list)

    @field_validator("booking_options", "exclusions", "required_assets", "goes_well_with", mode="before")
    @classmethod
    def coerce_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    @field_validator("programmatic", mode="before")
    @classmethod
    def coerce_programmatic(cls, v):
        if isinstance(v, bool):
            return "yes" if v else "no"
        return v

    @field_validator("ctr_pct")
    @classmethod
    def ctr_in_range(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0 <= v <= CTR_MAX_PCT):
            raise ValueError(f"CTR {v}% außerhalb plausibler Spanne 0–{CTR_MAX_PCT}%")
        return v


class ChannelPortal(BaseModel):
    """Eine Marke (Portal) innerhalb eines Channels."""
    brand: str
    sub_areas: list[str] = Field(default_factory=list)
    stationary: bool = False
    mobile_avail: Literal["yes", "only_mew", "no"] = "no"

    @field_validator("sub_areas", mode="before")
    @classmethod
    def coerce_sub_areas(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        return v


class ChannelDemographics(BaseModel):
    male_pct: Optional[int] = None
    employed_pct: Optional[int] = None
    higher_education_pct: Optional[int] = None
    hhne_3000_plus_pct: Optional[int] = None

    @field_validator("male_pct", "employed_pct", "higher_education_pct", "hhne_3000_plus_pct")
    @classmethod
    def pct_in_range(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and not (0 <= v <= 100):
            raise ValueError(f"Prozentwert {v} außerhalb 0–100")
        return v


class Channel(BaseModel):
    """Ein thematischer Channel, z. B. 'Technology' oder 'Football'."""
    name: str
    portals: list[ChannelPortal] = Field(default_factory=list)
    demographics: Optional[ChannelDemographics] = None
    reach_stationary_mio: Optional[float] = None
    reach_mobile_mio: Optional[float] = None
    reach_multiscreen_mio: Optional[float] = None


class PriceRule(BaseModel):
    """Eine Zelle der CPM-Preismatrix: Format-Gruppe x Paket -> Preis."""
    package_group: str = Field(..., description="z. B. 'Mobile Content Ad 2:1'")
    booking_type: str = Field(..., description="z. B. 'RoC' (Run of Channel)")
    cpm_euro: int

    @field_validator("cpm_euro")
    @classmethod
    def cpm_in_range(cls, v: int) -> int:
        if not (CPM_MIN_EUR <= v <= CPM_MAX_EUR):
            raise ValueError(f"CPM {v}€ außerhalb plausibler Spanne {CPM_MIN_EUR}–{CPM_MAX_EUR}€")
        return v


# Container für das Ergebnis einer Dokument-Extraktion.
class ExtractionResult(BaseModel):
    ad_formats: list[AdFormat] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    price_rules: list[PriceRule] = Field(default_factory=list)
