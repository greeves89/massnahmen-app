# Maßnahmen-Auswertung

Single-User-Webapp zur Erfassung und Auswertung von Berufs- und Studienorientierungs-Maßnahmen (BSO) an Schulen — orientiert am offiziellen Formular „Antrag und Nachweis zur Wahrnehmung eines Angebots im Rahmen der Berufs- und Studienorientierung".

## Funktionen

- 🔐 Login (Single-User, beim ersten Start automatisch angelegt)
- 📋 Maßnahmen erfassen mit allen Original-Formularfeldern:
  - Antrag auf Freistellung (Schüler:in, Angebot, Datum, 1./2./3. Freistellung)
  - Beurlaubungs-Entscheidung (erteilt/nicht erteilt + Begründung)
  - Bestätigung der Teilnahme (Institution, Datum, Stempel oder E-Mail-Vermerk)
  - Rückmeldung mit 5 Smiley-Bewertungen (😊 😐 😞)
  - Kenntnisnahme (Tutor + Sorgeberechtigte)
- 📊 Dashboard nach Schuljahr (1.8.–31.7.) mit Bewertungs-Aggregat pro Frage
- 📈 Gesamtdurchschnitt pro Schuljahr und pro Maßnahme

## Stack

- **Backend**: FastAPI + SQLAlchemy (async) + SQLite + Jinja2
- **Frontend**: Tailwind CSS (CDN) + HTMX
- **Auth**: Session-Cookies (signiert, HttpOnly via SessionMiddleware)
- **Deploy**: Docker + docker-compose, ein einziger Container, SQLite-Volume

## Lokal starten

```bash
cp .env.example .env
# SECRET_KEY und INITIAL_ADMIN_PASSWORD setzen, dann:
python -c "import secrets; print(secrets.token_urlsafe(48))"  # für SECRET_KEY

docker compose up -d --build
```

App läuft auf http://localhost:8090

Einloggen mit der E-Mail aus `INITIAL_ADMIN_EMAIL` und dem Passwort aus `INITIAL_ADMIN_PASSWORD`.

## Datenmodell — Smiley-Bewertung

Jede Bewertungsfrage wird intern als Integer gespeichert:

| Wert | Bedeutung |
|------|-----------|
|  `1` | 😊 positiv |
|  `0` | 😐 neutral |
| `-1` | 😞 negativ |
| `null` | nicht bewertet |

Der Durchschnitt wird auf einem Smiley-Symbol gerundet:
- `>= 0.34` → 😊
- `<= -0.34` → 😞
- sonst → 😐

## Schuljahr-Logik

Das Schuljahr läuft vom **1. August** bis **31. Juli**. Bei der Anlage einer Maßnahme wird das Schuljahr automatisch aus dem Datum bestimmt, kann aber manuell überschrieben werden (z.B. für rückwirkende Erfassung).

## Routes

| Methode | Pfad | Zweck |
|---------|------|-------|
| GET | `/` | Dashboard mit Statistik pro Schuljahr |
| GET / POST | `/login`, `/logout` | Authentifizierung |
| GET / POST | `/massnahmen/neu` | Neue Maßnahme anlegen |
| GET | `/massnahmen/{id}` | Detail + Bearbeitung |
| POST | `/massnahmen/{id}/edit` | Basis-Daten ändern |
| POST | `/massnahmen/{id}/beurlaubung` | Beurlaubungs-Status |
| POST | `/massnahmen/{id}/teilnahme` | Teilnahme-Bestätigung |
| POST | `/massnahmen/{id}/bewertung` | Smiley-Bewertung |
| POST | `/massnahmen/{id}/kenntnis` | Kenntnisnahme-Datumsfelder |
| POST | `/massnahmen/{id}/loeschen` | Maßnahme entfernen |
| GET | `/healthz` | Health-Check für Reverse-Proxy |

## Deployment

Reverse-Proxy (nginx) auf den Port 8090 zeigen lassen, z.B.:

```nginx
location / {
    proxy_pass http://127.0.0.1:8090;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

SSL via Let's Encrypt (certbot). Für die SQLite-Datenbank reicht ein Docker-Volume — Backup per `docker cp` oder `docker compose exec app cp /data/massnahmen.db /backup/`.

## Lizenz

Privat-Projekt.
