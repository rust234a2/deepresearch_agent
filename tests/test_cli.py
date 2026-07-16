import pytest

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


def test_cli_eval_entity_prints_metrics(company_database_path, capsys):
    main(
        [
            "eval", "entity",
            "--database", str(company_database_path),
            "--cases", "evals/procurement/entity_resolution.synthetic.yaml",
        ]
    )
    out = capsys.readouterr().out
    assert "entity resolution" in out
    assert "accuracy=1.00" in out


def test_cli_question_path_still_works(company_database_path, tmp_path, capsys):
    main(
        [
            "核验示例科技股份有限公司",
            "--database", str(company_database_path),
            "--index", str(tmp_path / "missing.faiss"),
        ]
    )
    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out


def test_cli_trace_flag_parses_and_runs(company_database_path, tmp_path, capsys):
    pytest.importorskip("opentelemetry")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from deepresearch_agent.observability import configure_tracing, reset_tracing

    reset_tracing()
    configure_tracing(exporter=InMemorySpanExporter())  # 幂等：main 内 configure 不覆盖，避免碰 OTLP 网络
    try:
        main(
            [
                "核验示例科技股份有限公司",
                "--database", str(company_database_path),
                "--index", str(tmp_path / "missing.faiss"),
                "--trace",
            ]
        )
    finally:
        reset_tracing()
    out = capsys.readouterr().out
    assert "示例科技股份有限公司" in out
    assert "insufficient_evidence" in out


def test_cli_eval_perturb_prints_type_table(company_database_path, capsys):
    main(
        [
            "eval", "perturb",
            "--database", str(company_database_path),
            "--cases", "evals/procurement/perturbation.synthetic.yaml",
        ]
    )
    out = capsys.readouterr().out
    assert "perturbation robustness" in out
    assert "drop_suffix" in out
    assert "transpose" in out
    assert "overall_recovery=" in out
    # 红线：不泄露企业名
    assert "示例科技" not in out
