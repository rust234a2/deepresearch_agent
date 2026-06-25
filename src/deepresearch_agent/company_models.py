from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def none_if_blank(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def split_pipe(value: object) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split("|") if item.strip()]


class CompanyProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_name: str
    legal_name: str
    registration_status: str | None = None
    unified_social_credit_code: str
    legal_representative: str | None = None
    company_type: str | None = None
    registered_capital_amount: Decimal | None = None
    registered_capital_currency: str | None = None
    registered_capital_original: str | None = None
    paid_in_capital_amount: Decimal | None = None
    paid_in_capital_currency: str | None = None
    paid_in_capital_original: str | None = None
    established_date: date | None = None
    business_term_start: date | None = None
    business_term_end: date | None = None
    business_term_indefinite: bool = False
    registered_address: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    registration_authority: str | None = None
    gb_industry_section: str | None = None
    gb_industry_division: str | None = None
    gb_industry_group: str | None = None
    gb_industry_class: str | None = None
    enterprise_size: str | None = None
    business_scope: str | None = None
    aliases: list[str] = Field(default_factory=list)
    english_name: str | None = None
    website: str | None = None
    employee_count: int | None = Field(default=None, ge=0)
    employee_count_report_year: int | None = Field(default=None, ge=1900)
    latest_annual_report_year: int | None = Field(default=None, ge=1900)
    taxpayer_qualification: str | None = None

    @field_validator("aliases", mode="before")
    @classmethod
    def parse_aliases(cls, value: object) -> list[str]:
        return split_pipe(value)

    @field_validator(
        "registration_status",
        "legal_representative",
        "company_type",
        "registered_capital_amount",
        "registered_capital_currency",
        "registered_capital_original",
        "paid_in_capital_amount",
        "paid_in_capital_currency",
        "paid_in_capital_original",
        "established_date",
        "business_term_start",
        "business_term_end",
        "registered_address",
        "province",
        "city",
        "district",
        "registration_authority",
        "gb_industry_section",
        "gb_industry_division",
        "gb_industry_group",
        "gb_industry_class",
        "enterprise_size",
        "business_scope",
        "english_name",
        "website",
        "employee_count",
        "employee_count_report_year",
        "latest_annual_report_year",
        "taxpayer_qualification",
        mode="before",
    )
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)


class CompanyContact(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    unified_social_credit_code: str
    legal_name: str
    phones: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    mailing_address: str | None = None

    @field_validator("phones", "emails", mode="before")
    @classmethod
    def parse_multi_values(cls, value: object) -> list[str]:
        return split_pipe(value)

    @field_validator("mailing_address", mode="before")
    @classmethod
    def parse_mailing_address(cls, value: object) -> object:
        return none_if_blank(value)


class CompanyRecord(BaseModel):
    profile: CompanyProfile
    contact: CompanyContact | None = None


class CompanyResolutionCandidate(BaseModel):
    legal_name: str
    unified_social_credit_code: str


class CompanyResolution(BaseModel):
    status: Literal["resolved", "ambiguous", "not_found"]
    legal_name: str | None = None
    unified_social_credit_code: str | None = None
    matched_text: str | None = None
    match_type: Literal["legal_name", "alias"] | None = None
    candidates: list[CompanyResolutionCandidate] = Field(default_factory=list)


class ScopeChunkRecord(BaseModel):
    chunk_id: int
    unified_social_credit_code: str
    legal_name: str
    section_label: str | None = None
    text: str


class ScopeIndexMetadata(BaseModel):
    embedding_model: str
    embedding_dim: int
    normalized: bool
    chunk_count: int
    built_at: str


class ShareholderRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    unified_social_credit_code: str
    shareholder_name: str
    shareholder_credit_code: str | None = None
    shareholder_type: str | None = None
    shareholder_is_person: bool
    share_class: str | None = None
    shares_held: str | None = None
    indirect_holding_pct: str | None = None
    associated_product: str | None = None

    @field_validator("shareholder_is_person", mode="before")
    @classmethod
    def parse_is_person(cls, value: object) -> bool:
        return value is True or value == "true"

    @field_validator(
        "shareholder_credit_code",
        "shareholder_type",
        "share_class",
        "shares_held",
        "indirect_holding_pct",
        "associated_product",
        mode="before",
    )
    @classmethod
    def parse_blanks(cls, value: object) -> object:
        return none_if_blank(value)
