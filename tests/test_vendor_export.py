from deepresearch_agent.vendor_export import clean_cell, unquote


def test_unquote_strips_excel_text_wrapper():
    assert unquote('="泰尔股份"') == "泰尔股份"
    assert unquote("  普通值  ") == "普通值"
    assert unquote('=""') == ""


def test_clean_cell_treats_dash_and_stars_as_missing():
    assert clean_cell('="-"') == ""
    assert clean_cell("-") == ""
    assert clean_cell('="***"') == ""
    assert clean_cell('="工业设备制造"') == "工业设备制造"
