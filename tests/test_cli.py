from deepresearch_agent.cli import main


def test_cli_prints_source_backed_company_report(company_database_path, tmp_path, capsys):
    main(
        [
            "核验示例科技股份有限公司",
            "--database",
            str(company_database_path),
            "--index",
            str(tmp_path / "missing.faiss"),
        ]
    )

    output = capsys.readouterr().out
    assert "示例科技股份有限公司" in output
    assert "insufficient_evidence" in output
    assert "Evidence" in output


def test_cli_renders_supplier_report_for_named_company(company_database_path, tmp_path, capsys):
    main(
        [
            "核验示例科技股份有限公司",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )

    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "insufficient_evidence" in out


def test_cli_renders_scope_unavailable_for_capability_question(company_database_path, tmp_path, capsys):
    main(
        [
            "哪些企业能做注塑成型",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )

    out = capsys.readouterr().out
    assert "不可用" in out
    assert "insufficient_evidence" in out
