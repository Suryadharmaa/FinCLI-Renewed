"""Local user profile and gameplay rules."""

from __future__ import annotations

from dataclasses import dataclass

from fincli.app.storage.database import FinCLIDatabase


@dataclass(frozen=True, slots=True)
class UserProfile:
    name: str
    equity: float
    currency: str
    leverage: str
    years_in_investment: float
    gameplay: str


class UserProfileService:
    """Persist one local profile used to tailor /analyze risk context."""

    def __init__(self, db: FinCLIDatabase) -> None:
        self.db = db

    def save(self, name: str, equity: float, currency: str, leverage: str, years: float) -> UserProfile:
        profile = UserProfile(
            name=name.strip(),
            equity=float(equity),
            currency=currency.strip().upper(),
            leverage=leverage.strip(),
            years_in_investment=float(years),
            gameplay=classify_gameplay(float(equity)),
        )
        self.db.execute(
            """
            INSERT INTO user_profile (id, name, equity, currency, leverage, years_in_investment, gameplay, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                equity=excluded.equity,
                currency=excluded.currency,
                leverage=excluded.leverage,
                years_in_investment=excluded.years_in_investment,
                gameplay=excluded.gameplay,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                profile.name,
                profile.equity,
                profile.currency,
                profile.leverage,
                profile.years_in_investment,
                profile.gameplay,
            ),
        )
        return profile

    def get(self) -> UserProfile | None:
        rows = self.db.query("SELECT * FROM user_profile WHERE id = 1")
        if not rows:
            return None
        row = rows[0]
        return UserProfile(
            name=str(row["name"]),
            equity=float(row["equity"]),
            currency=str(row["currency"]),
            leverage=str(row["leverage"]),
            years_in_investment=float(row["years_in_investment"]),
            gameplay=str(row["gameplay"]),
        )

    def clear(self) -> None:
        self.db.execute("DELETE FROM user_profile WHERE id = 1")


def classify_gameplay(equity: float) -> str:
    if equity <= 400:
        return "Scalper"
    if equity <= 1000:
        return "Intra day"
    if equity <= 5000:
        return "Day trade"
    return "Swing/Investor"
