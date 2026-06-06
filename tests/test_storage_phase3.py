from pathlib import Path

from fincli.app.storage.database import FinCLIDatabase


def test_database_connections_do_not_lock_file_after_operations(tmp_path: Path) -> None:
    db_file = tmp_path / "fincli.db"
    db = FinCLIDatabase(db_file)

    db.execute("INSERT OR REPLACE INTO watchlist(symbol, group_name) VALUES (?, ?)", ("AAPL", "default"))
    rows = db.query("SELECT symbol FROM watchlist")

    assert rows[0]["symbol"] == "AAPL"
    db_file.unlink()
    assert not db_file.exists()
