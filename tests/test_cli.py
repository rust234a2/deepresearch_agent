from deepresearch_agent.cli import main


def test_cli_prints_source_backed_company_report(company_database_path, capsys):
    main(
        [
            "核验示例科技股份有限公司",
            "--database",
            str(company_database_path),
        ]
    )

    output = capsys.readouterr().out
    assert "示例科技股份有限公司" in output
    assert "insufficient_evidence" in output
    assert "Evidence" in output
