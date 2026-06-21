from pathlib import Path

from scripts.build_company_database import main


FIXTURES = Path(__file__).parent / "fixtures" / "procurement"


def test_build_company_database_cli_writes_database_and_summary(tmp_path, capsys):
    database_path = tmp_path / "companies.sqlite3"

    main(
        [
            "--companies",
            str(FIXTURES / "companies.csv"),
            "--contacts",
            str(FIXTURES / "contacts.csv"),
            "--output",
            str(database_path),
        ]
    )

    assert database_path.exists()
    assert capsys.readouterr().out.strip() == "companies=1 contacts=1"
