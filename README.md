# pretix-mailwizz

Newsletter-Anmeldung im pretix-Bestellprozess mit MailWizz-Anbindung.

Das Plugin zeigt im Checkout (Kontaktformular) eine **optionale, nicht
vorausgewählte** Newsletter-Checkbox. Nur wenn die Kundin oder der Kunde
aktiv zustimmt, wird die E-Mail-Adresse nach Abschluss der Bestellung über
die MailWizz-API in eine konfigurierbare Liste eingetragen. Ist für die
Liste in MailWizz **Double Opt-In** aktiviert, verschickt MailWizz die
Bestätigungs-E-Mail – das Plugin erzwingt niemals bestätigte Subscriber
und umgeht den Double-Opt-In-Prozess nicht.

## Funktionsweise

1. **Checkout**: Über das pretix-Signal `contact_form_fields` wird dem
   Kontaktformular die Checkbox `pretix_mailwizz_newsletter_optin`
   hinzugefügt (freiwillig, nie vorausgewählt). pretix speichert den Wert
   automatisch in `order.meta_info['contact_form_data']`.
2. **Bestellung abgeschlossen** (`order_placed`): Bei aktiver Zustimmung
   wird die Einwilligung dokumentiert (Zeitpunkt, verwendeter
   Einwilligungstext, Sprache, Listen-UID in `order.meta_info`) und ein
   Eintrag im separaten Sync-Log (`NewsletterSyncLog`) angelegt.
3. **Asynchroner Sync**: Nach dem Commit der Bestellung wird ein
   Celery-Task (pretix-Background-Task-Struktur) gestartet, der den
   Subscriber per `POST /lists/{LIST_UID}/subscribers` anlegt. Temporäre
   Fehler werden mit exponentiellem Backoff erneut versucht.
4. **Idempotenz**: Pro (Event, Bestellcode, E-Mail, Liste) existiert
   maximal ein Sync-Eintrag (Unique Constraint). Bereits erfolgreiche
   Einträge werden nie erneut gesendet. Vor dem Anlegen wird die Liste
   per `search-by-email` geprüft:
   - `confirmed`/`unconfirmed` → als Erfolg („already exists") behandelt
   - `unsubscribed` → wird **standardmäßig nicht reaktiviert**
     (konfigurierbar)

Der Checkout schlägt **niemals** fehl, weil MailWizz nicht erreichbar ist:
Die gesamte Verarbeitung ist vom Bestellvorgang entkoppelt, alle Fehler
werden abgefangen, geloggt und im Sync-Log nachvollziehbar gemacht.

## Installation

Grundprinzip: Das Plugin muss in **dasselbe Python-Environment wie
pretix** installiert werden. pretix erkennt es danach automatisch über
den Entry-Point – es ist keine Eintragung in eine Konfigurationsdatei
nötig. Anschließend: Migration ausführen und Webserver **und**
Celery-Worker neu starten.

> **Hinweis:** Das Plugin ist (noch) **nicht auf PyPI veröffentlicht**.
> Die einfachste Installation erfolgt direkt aus dem GitHub-Repository
> oder über das selbst gebaute Wheel (siehe „Paket bauen"):
>
> ```bash
> # Empfohlen: direkt aus GitHub installieren
> pip install git+https://github.com/brightcolor/pretix-mailwizz.git
>
> # Bestimmten Release-Tag (stabiler):
> pip install git+https://github.com/brightcolor/pretix-mailwizz.git@v1.0.0
>
> # Oder aus dem Quellverzeichnis / Wheel:
> pip install /pfad/zu/pretix-mailwizz
> pip install pretix_mailwizz-1.0.0-py3-none-any.whl
> ```

### Variante A: Manuelle Installation (pretix small-scale, virtualenv)

Bei einer Installation nach der offiziellen Anleitung
("small-scale manual deployment") liegt pretix in einem virtualenv unter
`/var/pretix/venv` und läuft als Benutzer `pretix`:

```bash
# 1. Plugin in das pretix-virtualenv installieren

#    Direkt aus GitHub (empfohlen):
sudo -u pretix /var/pretix/venv/bin/pip install \
  git+https://github.com/brightcolor/pretix-mailwizz.git@v1.0.0

#    Oder aus einem lokal kopierten Wheel:
sudo -u pretix /var/pretix/venv/bin/pip install /tmp/pretix_mailwizz-1.0.0-py3-none-any.whl

#    Oder aus dem Quellverzeichnis (z. B. per Git ausgecheckt):
sudo -u pretix /var/pretix/venv/bin/pip install /pfad/zu/pretix-mailwizz

# 2. Datenbank-Migration ausführen (legt die Sync-Log-Tabelle an)
sudo -u pretix /var/pretix/venv/bin/python -m pretix migrate

# 3. pretix neu starten – Web UND Worker!
sudo systemctl restart pretix-web pretix-worker
```

Prüfen: Im pretix-Backend unter **Event → Einstellungen → Plugins** muss
„MailWizz Newsletter" erscheinen.

### Variante B: Docker (offizielles pretix-Image)

Das offizielle Image installiert Plugins über ein eigenes, davon
abgeleitetes Image. Eigenes `Dockerfile` anlegen:

```dockerfile
FROM pretix/standalone:stable
USER root
COPY pretix_mailwizz-1.0.0-py3-none-any.whl /tmp/
RUN pip3 install /tmp/pretix_mailwizz-1.0.0-py3-none-any.whl
#   oder aus lokalem Quellcode:
#   COPY pretix-mailwizz /pretix-mailwizz
#   RUN pip3 install /pretix-mailwizz
#   oder – erst nach Veröffentlichung auf PyPI:
#   RUN pip3 install pretix-mailwizz
USER pretixuser
RUN cd /pretix/src && make production
```

Bauen und ausrollen:

```bash
docker build -t mypretix .
# in docker-compose.yml bzw. den systemd-Units "pretix/standalone:stable"
# durch "mypretix" ersetzen, dann:
docker compose down && docker compose up -d

# Migration im laufenden Container (einmalig nach der Installation):
docker exec -it pretix.service pretix migrate
```

Wichtig: Web- **und** Worker-Container müssen das neue Image verwenden,
sonst kennt der Celery-Worker den Sync-Task nicht.

### Variante C: Entwicklung / lokale Instanz

```bash
git clone https://github.com/brightcolor/pretix-mailwizz.git
cd pretix-mailwizz
pip install -e ".[dev]"      # editierbar, im selben venv wie pretix
python -m pretix migrate     # bzw. mit gesetztem PRETIX_CONFIG_FILE
```

`pip install -e` reicht – Codeänderungen wirken nach einem
Server-Neustart sofort, ohne Neuinstallation.

### pretix Hosted (pretix.eu)

Auf pretix.eu können nur von pretix freigegebene Marketplace-Plugins
genutzt werden. Dieses Plugin ist für selbst gehostete Instanzen
gedacht; für Hosted müsste es im pretix Marketplace veröffentlicht und
geprüft werden.

## Aktivierung in pretix

Das Plugin ist ein Hybrid-Plugin (Organizer- und Event-Ebene):

1. **Veranstalter-Ebene**: Veranstalter → Plugins → **MailWizz Newsletter**
   aktivieren (schaltet die Integration für den Veranstalter frei).
2. **Event-Ebene**: Im Event unter **Einstellungen → Plugins →
   MailWizz Newsletter** aktivieren.
3. Unter **Einstellungen → MailWizz Newsletter** (Event) bzw.
   **Veranstalter → MailWizz Newsletter** die Verbindung konfigurieren.

## Konfiguration in pretix

Einstellungen gibt es auf zwei Ebenen:

* **Veranstalter-Ebene** (Veranstalter → MailWizz Newsletter):
  organizer-weite Standardwerte.
* **Event-Ebene** (Event → Einstellungen → MailWizz Newsletter):
  überschreibt einzelne Werte. Leere Felder fallen automatisch auf die
  Veranstalter-Ebene zurück (pretix-Settings-Hierarchie).

| Einstellung | Bedeutung |
|---|---|
| Integration aktivieren | Master-Schalter für das Plugin |
| Checkbox anzeigen | Checkbox im Checkout ein-/ausblenden |
| Einwilligungstext | Checkbox-Label, mehrsprachig pflegbar |
| Hilfetext | Optionaler Text unter der Checkbox |
| API-Basis-URL | z. B. `https://newsletter.example.org/api` |
| API-Schlüssel | Wird nach dem Speichern nie wieder angezeigt |
| Listen-UID | Ziel-Liste in MailWizz |
| Feld-Tags | Mapping für Vorname, Nachname, Eventname, Bestellcode |
| Timeout / Retries | HTTP-Timeout und Wiederholungsversuche |
| Abgemeldete reaktivieren | Standard: **nein** |
| Debug-Logging | Protokolliert Methode/Pfad/Statuscode, keine Inhalte |

Mit **„Verbindung testen"** auf der Event-Einstellungsseite werden URL,
Schlüssel und Listen-UID gegen die MailWizz-API geprüft. Darunter zeigt
die Seite die letzten Sync-Einträge inkl. Fehlern (E-Mail-Adressen
maskiert).

Vorname/Nachname werden – falls vorhanden – aus der Rechnungsadresse der
Bestellung übernommen und nur übertragen, wenn ein Feld-Tag konfiguriert
ist.

### Beispiel für den Checkbox-Text

> Ich möchte den Newsletter abonnieren und über Neuigkeiten, Events und
> Angebote informiert werden. Ich kann mich jederzeit wieder abmelden.

## Konfiguration in MailWizz

1. **API aktivieren** und einen API-Schlüssel erzeugen
   (das Plugin sendet ihn als `X-Api-Key`-Header; für MailWizz 1.x wird
   zusätzlich `X-MW-PUBLIC-KEY` gesetzt).
2. Die **Listen-UID** der Zielliste kopieren (Übersichtsseite der Liste).
3. **Wichtig:** In den Listeneinstellungen **Double Opt-In aktivieren**
   (Opt-in: *double*). Nur dann verschickt MailWizz die
   Bestätigungs-E-Mail. Das Plugin legt Subscriber regulär an und
   erzwingt keinen bestätigten Status.
4. Falls Feld-Tags wie `EVENTNAME` oder `ORDERCODE` verwendet werden,
   müssen diese Custom Fields in der Liste existieren.

## Datenschutz (DSGVO)

* Die Checkbox ist freiwillig und **nie vorausgewählt**; ohne aktive
  Einwilligung findet **keine** Übertragung an MailWizz statt.
* Der zum Bestellzeitpunkt aktive Einwilligungstext wird zusammen mit
  Zeitpunkt und Sprache in der Bestellung (`meta_info`) und im Sync-Log
  gespeichert (Rechenschaftspflicht, Art. 5 Abs. 2 DSGVO).
* **IP-Adressen werden nicht gespeichert.**
* Bestelldaten und Newsletter-Sync-Daten sind getrennt (eigenes
  Sync-Log-Modell).
* Logs sind datensparsam: E-Mail-Adressen werden maskiert
  (`m***@example.org`), der API-Schlüssel erscheint nie in Logs, volle
  API-Responses werden nicht protokolliert.
* Die Newsletter-**Abmeldung** läuft ausschließlich über MailWizz
  (Abmeldelink in den Newslettern); das Plugin verwaltet keine
  Abmeldungen in pretix.
* **Hinweis:** Die rechtliche Prüfung des Einwilligungstextes, der
  Datenschutzhinweise und der gesamten Newsletter-Prozesse liegt beim
  Betreiber. Dieses Plugin liefert nur die technische Grundlage und
  ersetzt keine Rechtsberatung.

## Troubleshooting

| Symptom | Ursache / Lösung |
|---|---|
| Checkbox erscheint nicht | Plugin im Event aktiviert? Integration eingeschaltet? API-URL, Schlüssel und Listen-UID vollständig? (Ohne vollständige Konfiguration wird die Checkbox bewusst nicht angezeigt.) |
| Sync bleibt `pending` | Läuft der Celery-Worker? Eintrag wird beim nächsten Task-Lauf verarbeitet. |
| Sync `failed` | Fehlermeldung in der Sync-Tabelle prüfen; „Verbindung testen" nutzen. Temporäre Fehler werden automatisch erneut versucht. |
| Subscriber ohne Bestätigungsmail | Double Opt-In in der MailWizz-Liste aktivieren. |
| `skipped` | Kontakt hat sich zuvor abgemeldet und wird absichtlich nicht reaktiviert. |

## Logs

Das Plugin loggt unter dem Logger-Namespace `pretix_mailwizz.*` in das
normale pretix/Django-Logging. Debug-Logging (Einstellung) ergänzt
Methode, Pfad und HTTP-Statuscode je API-Aufruf – nie Schlüssel,
Response-Bodies oder unmaskierte E-Mail-Adressen.

## Tests

```bash
pip install -e ".[dev]"
python -m pytest
```

Die Tests laufen gegen `pretix.testutils.settings` (SQLite) und mocken
alle HTTP-Requests – es wird nie eine echte MailWizz-Instanz kontaktiert,
und es sind keine echten Zugangsdaten enthalten.

## Updates

* Vor dem Update den Changelog (`CHANGELOG.md`) prüfen.
* Update einspielen (analog zur Installation):

  ```bash
  # Manuell (neues Wheel bauen/kopieren, dann):
  sudo -u pretix /var/pretix/venv/bin/pip install -U /tmp/pretix_mailwizz-<version>-py3-none-any.whl
  sudo -u pretix /var/pretix/venv/bin/python -m pretix migrate
  sudo systemctl restart pretix-web pretix-worker

  # Docker: Image neu bauen (siehe Installation), Container neu erstellen,
  # danach: docker exec -it pretix.service pretix migrate
  ```

* Die Kompatibilität ist als `pretix>=2025.10` deklariert; pretix
  verweigert das Laden bei inkompatiblen Versionen.

## Paket bauen (zur Weitergabe)

```bash
cd pretix-mailwizz
pip install build pretix-plugin-build
python -m build          # erzeugt dist/pretix_mailwizz-1.0.0-py3-none-any.whl
```

Das Wheel kann dann auf dem Zielserver direkt installiert werden:
`pip install pretix_mailwizz-1.0.0-py3-none-any.whl`

## Lizenz

MIT – siehe [LICENSE](LICENSE).
