# Luuri – B2B-soittotyökalu

Ulossoittojärjestelmä (LeadDesk-tyylinen) Muutto365:n myyntipalvelulle:
tekoäly prospektoi yritykset ja etsii päättäjän yhteystiedot, ihminen soittaa
ja kirjaa, myydyt bookkaukset ja kaikki tapahtumat virtaavat CRM:ään ja muihin
järjestelmiin outbox-mallilla.

Pino: FastAPI + Postgres (SQL-migraatiot, ei ORM) + Vue 3/Pinia. Sama rakenne
ja samat konventiot kuin movingfirm-backend/-admin.

## Mitä se tekee

| Osa | Mitä |
|---|---|
| **Soita** | Jonosta seuraava yritys ja päättäjä, spiikki, `tel:`-linkki (ihminen soittaa omalla puhelimella), lopputulos yhdellä klikillä, takaisinsoitot, bookkauksen kirjaus. Yksi yritys on kerrallaan vain yhdellä soittajalla (15 min lease). |
| **Prospektointi** | Agentti hakee yritykset PRH:n avoimesta datasta (paikkakunta, toimiala, nimi, yhtiömuoto), lukee verkkosivut ja ehdottaa yhteystiedot. Claude (valinnainen) nimeää päättäjän ja pisteyttää sopivuuden; Brave Search (valinnainen) löytää verkkosivun niille, joilla sitä ei ole rekisterissä. **Mitään ei soiteta ennen kuin ihminen hyväksyy.** |
| **Yritykset** | CRM-näkymä: yhteyshenkilöt, soittohistoria, bookkaukset, CSV-tuonti, ei-saa-soittaa-lista. |
| **Kampanjat** | Mitä myydään + spiikki + soittosäännöt (max yrityksiä, uusintasoiton viive). |
| **Bookkaukset** | Myydyt bookkaukset tiloineen (bookattu → vahvistettu → pidetty / peruttu / ei saapunut). |
| **Raportit** | Soittaja-, lopputulos- ja päiväkohtaiset luvut. Vain mitattuja asioita. |
| **Integraatiot** | Outbox + kohteet: webhook, movingfirm-backend, Twenty, analytiikka. Toimitusloki ja uudelleenyritys. |
| **Käyttäjät** | Roolit `admin` / `sales`, API-avaimet muille järjestelmille (`read` / `write` / `admin`). |

## Käynnistys

```bash
cp .env.example .env     # täytä SESSION_SECRET ja BOOTSTRAP_ADMIN_*
docker compose up --build
# → http://localhost:8080  (kirjaudu BOOTSTRAP_ADMIN_EMAIL / _PASSWORD)
```

Ensimmäinen admin luodaan envistä kun `users`-taulu on tyhjä. Luo sen jälkeen
myyjät Käyttäjät-sivulta.

Kehitys ilman Dockeria:

```bash
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg2://…  SESSION_SECRET=dev
python migrate.py && uvicorn app.main:app --reload   # API :8000
python worker.py                                      # outbox + prospektointi
cd frontend && npm install && npm run dev             # UI :5173, proxy /api → :8000
pytest                                                # vaatii Postgresin (DATABASE_URL)
```

## Arkkitehtuuri

```
frontend (Vue)  ──/api──▶  app.main (FastAPI)  ──▶  Postgres
                                 │  jokainen liiketoimintamuutos kirjoittaa
                                 ▼  outbox_events-rivin SAMASSA transaktiossa
                            worker.py ──▶ integration_targets ──▶ webhook / movingfirm / Twenty / analytics
                                 └──▶ prospecting_runs ──▶ PRH ▶ verkkosivut ▶ (Claude) ▶ prospects
```

- `migrations/NNN_*.sql` – expand-only, uudelleenajettavat, ajetaan `migrate`-
  palvelussa ennen appia (sama sääntö kuin movingfirm: uusi tiedosto aina, ei
  muokata vanhoja, ensimmäinen rivi `-- expand_only: true`).
- `app/routers/` – `session` (login, käyttäjät, API-avaimet), `companies`,
  `campaigns` (+ jonoon lisäys), `calls` (jono, soitot, bookkaukset, tilastot),
  `prospecting`, `integrations`.
- `app/services/outbox.py` – `emit()` + tapahtumaluettelo.
- `app/services/integrations/base.py` – adapterit; uusi järjestelmä = uusi
  `Adapter`-aliluokka + rivi `ADAPTERS`:iin + CHECK-laajennus migraatiossa.
- `app/services/prospecting/` – `prh.py` (rekisteri), `websearch.py` (Brave),
  `enrich.py` (sivut + Claude), `runner.py` (ajo).

## Tapahtumat (outbox)

`company.created`, `company.updated`, `contact.created`, `call.logged`,
`booking.created`, `booking.updated`, `prospecting.run_finished`,
`prospect.approved`.

Webhook-payload:

```json
{ "id": "…", "type": "booking.created", "aggregate_type": "booking", "aggregate_id": "…",
  "occurred_at": "2026-10-22T14:00:00+00:00", "source": "luuri",
  "data": { "...booking row...", "company": {…}, "contact": {…}, "seller_name": "…" } }
```

Otsikot `X-Luuri-Event`, `X-Luuri-Timestamp`, `X-Luuri-Signature: sha256=HMAC(secret, "{ts}.{body}")`.
Vastaanottaja vastaa 2xx; muuten uudelleenyritys 1 → 2 → 5 → 15 → 30 → 60 → 120 → 240 min, sitten `dead` (UI:sta voi yrittää uudelleen).

### Kohteet

| kind | Mitä tekee | Konfiguraatio (config-JSON) | Salaisuus |
|---|---|---|---|
| `webhook` | Allekirjoitettu POST | `url`, `secret_env` | env-muuttuja jonka nimi on `secret_env` (oletus `WEBHOOK_SIGNING_SECRET`) |
| `movingfirm_internal` | Bookkaukset movingfirm-backendin sisäiseen API:in (`POST {base_url}{path}`, bearer) | `base_url` (oletus `MOVINGFIRM_BACKEND_URL`), `path` (oletus `/api/internal/crm/sales-bookings`) | `MOVINGFIRM_INTERNAL_TOKEN` |
| `twenty` | Company `company.created`:sta, Opportunity `booking.created`:sta | `base_url`, `stage` | `TWENTY_API_KEY` |
| `analytics` | Myyntitapahtumat olemassa olevaan `ux_events`-trackeriin | `url` (oletus `ANALYTICS_UX_EVENTS_URL`) | – |

Salaisuuksia ei voi tallentaa kohteen configiin; API hylkää avaimet joiden nimi
vihjaa salaisuuteen. Vain `secret_env`-viittaus.

**movingfirm-backend-puoli:** reittiä `/api/internal/crm/sales-bookings` ei
vielä ole. Pienin toteutus siellä: idempotentti upsert `crm_leads`-tyyliseen
tauluun avaimella `idempotency_key`, auth `INTERNAL_API_TOKEN`. Vaihtoehtoisesti
osoita `path` olemassa olevaan reittiin ja muokkaa `MovingfirmInternalAdapter`in
payload-mappausta.

## Analytiikan jatkuvuus

Org-sääntö: uusia mittareita ei jätetä hiljaa pois. `analytics`-kohde kirjaa
jokaisen tapahtuman olemassa olevaan trackeriin (`POST /api/ux-events`)
muodossa:

| ux_events-kenttä | arvo |
|---|---|
| `event_type` | `sales_call_logged`, `sales_booking_created`, `sales_booking_updated`, `sales_company_created`, … |
| `actor_type` | `sales_agent` (uusi arvo; sarakkeella ei ole CHECKiä tarkoituksella, ks. backend-migraatio 008) |
| `interaction_surface` | `luuri` (uusi arvo) |
| `session_id` | `luuri-{company_id}` |
| `event_data` | `luuri_event`, `aggregate_id`, `campaign_id`, `company_id`, `outcome`, `duration_seconds`, `booking_status`, `value_eur`, `caller` |

Admin-puolella nämä näkyvät `GET /internal/ux-events`-virrassa; funneliin
lisääminen = uusi vertical `admin.funnel_stages`-migraatiolla (ei tehty tässä).

## Soittaminen Luurilla (puhelinpalvelu)

Oletuksena soitto on `tel:`-linkki (oma puhelin). Kun `TELEPHONY_PROVIDER=46elks`
on asetettu, Soita-näkymässä on **Soita Luurilla** -nappi:

1. Luuri pyytää 46elksiä soittamaan **soittajan omaan numeroon** (Asetukset →
   Oma puhelinnumero; eSIM-numero käy).
2. Kun soittaja vastaa, 46elks soittaa asiakkaalle ja yhdistää puhelut.
   Asiakas näkee yrityksen numeron `TELEPHONY_FROM_NUMBER`, ei soittajan omaa.
3. Worker seuraa puhelun tilaa (`call_sessions`), UI näyttää
   "soitetaan sinulle → yhdistetään → käynnissä 1:23 → päättyi". Kesto ja
   hinta tallentuvat ja lopputuloksen kirjaus linkittyy puheluun.

Luuri on VPN:ssä ilman julkista osoitetta, joten webhookeja ei käytetä –
tila haetaan pollaamalla. Nauhoitus: `TELEPHONY_RECORD_CALLS=true`
(tarkista työsuhde-/tietosuojavaatimukset ennen käyttöönottoa).

Tarvittavat tunnukset (Ilari asettaa stackiin): `ELKS_API_USER`,
`ELKS_API_PASSWORD`, `TELEPHONY_FROM_NUMBER` (46elksistä ostettu
suomalainen numero, ~3 €/kk; puhelut ~0,02–0,05 €/min per leg, kaksi legiä).
Uusi operaattori = `Provider`-aliluokka `app/services/telephony/`.

## Tekoäly: Mira ennen Anthropicia

`app/services/llm.py` valitsee: `MIRA_AGENT_URL` asetettu → **Mira**
(Ilarin agenttiajo, miragen-runner: `POST /run/async`, `GET /runs/{id}`,
otsikko `X-Miragen-Token`), muuten `ANTHROPIC_API_KEY` → Claude suoraan,
muuten sääntöpohjainen poiminta. Prospektiin tallentuu `enriched_by`.

Mira-agentin vaatimukset: tekstipohjainen profiili ilman hyväksyntää
vaativia työkaluja, ohjeistettu vastaamaan pelkällä JSONilla (prompt pyytää
sitä ja parseri poimii ensimmäisen `{…}`-lohkon). Worker on liitetty
`miragen-net`-verkkoon, joten agenttiin viitataan konttinimellä.

## Muistiinpanot puhelun aikana ja kalenteri

- Soita-näkymän muistiinpanokenttä **tallentuu automaattisesti** (`call_drafts`,
  0,8 s viiveellä) – sivun lataus tai selaimen kaatuminen ei hukkaa mitään.
  Lopputulosta kirjatessa luonnos siirtyy puhelun muistiinpanoiksi.
- **Bookattu!** avaa tapaamislomakkeen: pikavalinnat seuraaville arkipäiville
  (klo 10/14), kesto, paikka (Teams/Meet/puhelin/paikan päällä), linkki,
  asiakkaan sähköposti, arvo, sovitut asiat.
- Jokaisesta bookkauksesta saa **.ics-tiedoston** (`GET /api/bookings/{id}/ics`)
  – avautuu Outlookissa, Googlessa ja Applessa, asiakas ATTENDEE-rivinä.
- Integraatiokohde **`google_calendar`** vie tapaamisen yhteiseen Google-
  kalenteriin service accountilla (`GOOGLE_SERVICE_ACCOUNT_JSON` +
  `GOOGLE_CALENDAR_ID` tai kohteen `calendar_id`; kalenteri jaettava service
  accountin sähköpostille). Siirto päivittää, peruutus poistaa tapahtuman.
  Service account ei voi kutsua osallistujia ilman domain-wide delegationia,
  joten asiakas saa kutsun .ics:nä.
- Tilat: bookattu tapaaminen → yritys `qualified`; `completed` → `customer`.

## Prospektoinnin lähteet ja rajat

- **PRH avoin data** (`avoindata.prh.fi`, ei avainta): nimi, Y-tunnus,
  yhtiömuoto, TOL-toimiala, osoite, verkkosivu jos rekisteröity. Lopetetut,
  konkurssi- ja selvitystilayritykset suodatetaan pois. Pienillä yrityksillä
  verkkosivu puuttuu rekisteristä usein → Brave Search -vaihe.
- **Verkkosivut**: etusivu + sieltä löytyvät yhteystieto-linkit + yleiset polut.
  Puhelinnumerot ja sähköpostit poimitaan tekstistä; Y-tunnukset, OVT-koodit ja
  placeholderit (`etunimi.sukunimi@`) karsitaan.
- **Claude** (`ANTHROPIC_API_KEY`): nimeää päättäjät, tiivistää mitä yritys
  tekee, pisteyttää sopivuuden kampanjan tuotteeseen. Ilman avainta ajetaan
  deterministinen versio (henkilökohtaiset sähköpostit → nimet).
- Kaikki löydökset ovat ehdotuksia `prospects`-taulussa kunnes ihminen hyväksyy.
  Hyväksyntä luo `companies`+`contacts`-rivit ja (valinnaisesti) jonotehtävän.

B2B-kylmäsoitto on Suomessa sallittua; ei-saa-soittaa-lista (`do_not_call`)
on silti pakollinen ja estää numeron kaikissa yrityksissä.

## Tietomalli

001: `users`, `api_keys`, `companies`, `contacts`, `do_not_call`, `campaigns`,
`call_tasks` (jono), `calls`, `sales_bookings`, `prospecting_runs`,
`prospects`, `outbox_events`, `integration_targets`, `integration_deliveries`.
002: `users.phone_e164`, `call_sessions` (puhelinpalvelun legit), `prospects.enriched_by`.
003: `call_drafts`, `sales_bookings.{duration_minutes,location,meeting_url,attendee_email,calendar_event_id,calendar_html_link}`, kohdetyyppi `google_calendar`.

## Seuraavat askeleet

1. Deploy Portainer-stackiksi (`docker-compose.yml`), `LUURI_IMAGE_TAG`.
2. movingfirm-backendiin `/api/internal/crm/sales-bookings` (tai mappaus).
3. Selaindialeri (Telnyx/46elks) `tel:`-linkin rinnalle, jos nauhoitus ja
   automaattinen kesto halutaan.
4. Sähköposti bookkausvahvistuksesta asiakkaalle (`booking.created` → SMTP-kohde).
