from datetime import date
from decimal import Decimal

from deepresearch_agent.company_models import CompanyContact, CompanyProfile


def test_company_profile_parses_cleaned_csv_values():
    profile = CompanyProfile.model_validate(
        {
            "source_name": "示例科技",
            "legal_name": "示例科技股份有限公司",
            "registration_status": "存续",
            "unified_social_credit_code": "91330000123456789X",
            "registered_capital_amount": "1000000",
            "registered_capital_currency": "CNY",
            "registered_capital_original": "100万元",
            "paid_in_capital_amount": "",
            "established_date": "2020-01-02",
            "business_term_start": "2020-01-02",
            "business_term_end": "",
            "business_term_indefinite": "true",
            "aliases": "示例设备有限公司|示例机械有限公司",
            "employee_count": "120",
            "business_scope": "工业设备制造；工业设备销售。",
        }
    )

    assert profile.registered_capital_amount == Decimal("1000000")
    assert profile.paid_in_capital_amount is None
    assert profile.established_date == date(2020, 1, 2)
    assert profile.business_term_indefinite is True
    assert profile.aliases == ["示例设备有限公司", "示例机械有限公司"]
    assert profile.employee_count == 120


def test_company_contact_parses_pipe_separated_values():
    contact = CompanyContact.model_validate(
        {
            "unified_social_credit_code": "91330000123456789X",
            "legal_name": "示例科技股份有限公司",
            "phones": "0571-12345678|400-123-4567",
            "emails": "info@example.cn|sales@example.cn",
            "mailing_address": "",
        }
    )

    assert contact.phones == ["0571-12345678", "400-123-4567"]
    assert contact.emails == ["info@example.cn", "sales@example.cn"]
    assert contact.mailing_address is None
