from pathlib import Path
import subprocess
import sys

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


def test_build_company_database_script_runs_without_installed_package(tmp_path):
    project_root = Path(__file__).parents[1]
    database_path = tmp_path / "companies.sqlite3"

    result = subprocess.run(
        [
            sys.executable,
            str(project_root / "scripts" / "build_company_database.py"),
            "--companies",
            str(FIXTURES / "companies.csv"),
            "--contacts",
            str(FIXTURES / "contacts.csv"),
            "--output",
            str(database_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "companies=1 contacts=1"
