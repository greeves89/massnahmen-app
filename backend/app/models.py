from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    massnahmen: Mapped[list["Massnahme"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Massnahme(Base):
    """Eine einzelne Berufs-/Studienorientierungs-Maßnahme."""

    __tablename__ = "massnahmen"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)

    # Antrag auf Freistellung
    schueler_name: Mapped[str] = mapped_column(String(255))
    angebot: Mapped[str] = mapped_column(String(500))
    angebot_datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    freistellung_nummer: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1, 2, 3
    schuljahr: Mapped[str] = mapped_column(String(9), index=True)  # z.B. "2025/2026"

    # Beurlaubungs-Entscheidung (Tutor)
    beurlaubung_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "erteilt" / "nicht_erteilt" / None
    beurlaubung_begruendung: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Bestätigung der Teilnahme
    teilnahme_bestaetigt: Mapped[bool] = mapped_column(default=False)
    teilnahme_datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    institution_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    bestaetigung_per_email: Mapped[bool] = mapped_column(default=False)
    anhang_dateiname: Mapped[str | None] = mapped_column(String(500), nullable=True)
    anhang_pfad: Mapped[str | None] = mapped_column(String(500), nullable=True)
    anhang_mimetype: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anhang_groesse: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Rückmeldung (Smiley: 1=positiv, 0=neutral, -1=negativ, NULL=nicht bewertet)
    bewertung_informativ: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bewertung_persoenlich: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bewertung_orientierung: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bewertung_empfehlung: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bewertung_entscheidung: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Kenntnisnahme
    kenntnis_tutor_datum: Mapped[date | None] = mapped_column(Date, nullable=True)
    kenntnis_eltern_datum: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Sonstiges
    notizen: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="massnahmen")

    @property
    def bewertungs_felder(self) -> dict[str, int | None]:
        return {
            "informativ": self.bewertung_informativ,
            "persoenlich": self.bewertung_persoenlich,
            "orientierung": self.bewertung_orientierung,
            "empfehlung": self.bewertung_empfehlung,
            "entscheidung": self.bewertung_entscheidung,
        }

    @property
    def bewertung_average(self) -> float | None:
        werte = [v for v in self.bewertungs_felder.values() if v is not None]
        if not werte:
            return None
        return sum(werte) / len(werte)
