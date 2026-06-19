from deepresearch_agent.cli import main


def test_cli_prints_supplier_report(capsys):
    main(["Assess ACME Sensors for industrial sensor procurement"])

    output = capsys.readouterr().out
    assert "ACME Sensors" in output
    assert "Recommendation:" in output
    assert "Evidence" in output
