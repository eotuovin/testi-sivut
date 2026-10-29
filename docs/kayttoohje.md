# Luuri – myyjän käyttöohje

Luuri on Muutto365:n soittotyökalu: löydät yritykset, soitat, kirjaat
lopputuloksen ja bookkaat tapaamiset. Osoite VPN:ssä: http://10.8.0.4:6770.
Kirjaudu omalla sähköpostilla ja salasanalla.

## Tänään-sivu

Kirjautumisen jälkeen avautuu **Tänään**: erääntyneet takaisinsoitot, jonon
koko, odottavat tehtävät, päivän luvut ja tulevat tapaamiset. Iso punainen
nappi vie soittamaan. Takaisinsoiton tai tapaamisen klikkaus avaa sen suoraan.

## Päivän kulku lyhyesti

1. **Soita** → *Anna seuraava* → puhelin näyttää yrityksen, henkilön ja numeron.
2. Soita (selaimessa kuulokkeilla, tai omalla puhelimella).
3. Kirjoita muistiinpanot sitä mukaa kun puhutte – ne tallentuvat itsestään.
4. Valitse lopputulos (näppäimet 1–0) → *Tallenna ja seuraava* (Ctrl+Enter).
5. Jos sovit tapaamisen: **Bookattu!** → täytä aika ja paikka → se menee Bookkauksiin.

Jonon loputtua: lisää yrityksiä Hausta, listalta tai Agentista.

Spiikissä voi käyttää muuttujia `{{etunimi}}`, `{{nimi}}`, `{{yritys}}`,
`{{paikkakunta}}`, `{{myyja}}`, `{{tuote}}` – Soita-näkymä täyttää ne
asiakkaan tiedoilla. Kampanjat-sivulla on valmis **Avora-kampanja**
spiikkeineen.

## Haku

Vasemmalla suodattimet (toimiala, paikkakunta, koko, yhteystiedot, tila),
oikealla tulokset. **Yritykset**-välilehti näyttää samassa listassa Luurin omat
yritykset ja koko kaupparekisterin osumat (merkitty *Rekisteri*).
**Henkilöt**-välilehti hakee tallennetuista yhteyshenkilöistä tittelin ja
tason mukaan.

Rastita rivit ja valitse yläpalkista:

| Nappi | Mitä tapahtuu |
|---|---|
| Lisää listaan | Kerää valitut nimettyyn listaan (Listat-sivu) |
| Sekvenssiin | Laittaa valitut sähköposti + soitto -ketjuun |
| Soittojonoon | Valitut kampanjan jonoon → näkyvät Soita-näkymässä |
| Vie CSV | Lataa valitut taulukkona |
| Merkitse tila | Vaihtaa monen yrityksen tilan kerralla (esim. *Ei sovi*) |
| Tallenna Luuriin | Tallentaa rekisteriosumat ilman listaa tai jonoa |
| Tallenna haku | Suodattimet talteen – näkyvät kaikille sivun yläreunassa |

Rekisteriosuman klikkaus avaa sivupaneelin, josta sen voi tallentaa ja avata.

## Listat

Lista on kasa yrityksiä tai henkilöitä, jonka kokoat hausta. Listalta: *Lisää
koko lista jonoon*, *Koko lista sekvenssiin*, *Vie CSV*, *Avaa haussa*.

## Soita

Kolme palstaa:

- **Vasen – asiakas.** Yrityksen tiedot (✎ muokkaa), tila, pysyvät
  muistiinpanot, henkilöt. Klikkaa henkilöä vaihtaaksesi kenelle soitat; *+
  Lisää* lisää uuden kesken puhelun. *Koko profiili* avaa yrityssivun.
- **Keskellä – puhelu.** Iso numero, *Soita selaimessa* (kuulokkeet) tai
  numero `tel:`-linkkinä omalle puhelimelle. Spiikki sen alla. *✓ Numero toimi*
  merkitsee numeron vahvistetuksi.
- **Oikealla – lopputulos.** Muistiinpanot ja neljä ryhmää:
  - *Ei tavoitettu*: Ei vastausta, Varattu, Vastaaja, Vaihde, Väärä numero →
    yritys jää jonoon ja tulee uudelleen kampanjan säännön mukaan.
  - *Jatko*: Soita uudelleen → valitse aika (pikanapit 1 h … 1 kk) → tehtävä
    palaa sinun jonoosi silloin ja näkyy *Omat takaisinsoitot* -listassa.
  - *Päätös*: Ei kiinnosta, On jo asiakas, Ei saa soittaa → käsitelty loppuun.
    *Ei saa soittaa* laittaa numeron kieltolistalle pysyvästi.
  - *Liidi*: **Bookattu!** → tapaamisen aika, kesto, paikka (Teams/puhelin/
    asiakkaan luona), arvo ja sovitut asiat.

Näppäimet: `1`–`9`, `0` valitsevat lopputuloksen ruudun järjestyksessä,
`Ctrl+Enter` tallentaa, `Esc` tyhjentää valinnan. Näppäimet eivät toimi, kun
kirjoitat kenttään.

Yläpalkissa näkyy jonon tilanne: montako jonossa nyt, montako takaisinsoittoa
on erääntynyt. *Palauta jonoon* luovuttaa yrityksen takaisin ilman kirjausta.

**Omat takaisinsoitot** -listassa rivin klikkaus (tai *Soita nyt →*) avaa juuri
sen puhelun heti. Erääntyneet näkyvät punaisella ja Soita-valikon merkissä.

## Selaimessa soittaminen

Kun puhelinpalvelu on käytössä, *Soita selaimessa* avaa puhelun kuulokkeisiin.
Ensimmäisellä kerralla selain kysyy luvan mikrofoniin – salli. Asiakas näkee
yrityksen numeron. *Mykistä* hiljentää oman mikrofonin, *Lopeta puhelu* katkaisee.

Nauhoitus: puhelu nauhoitetaan vain, jos rastitat lopputuloksessa *Kerroin
asiakkaalle, että puhelu tallennetaan*. Sano se puhelun alussa (kampanjan
tallennusilmoitus näkyy ruudulla). Nauhoite ja sen analyysi ilmestyvät
yritysprofiilin *Toiminta*-välilehdelle.

## Sekvenssit ja Tehtävät

Sekvenssi on ketju: esim. sähköposti → 2 pv → soitto → 3 pv → sähköposti →
soitto. *Uusi sekvenssi* tarjoaa valmiit pohjat toimialoittain; tekstit saa
muokata. Yritys laitetaan ketjuun Hausta, listalta tai yritysprofiilista.

- Soittoaskel ilmestyy Soita-jonoon etusijalla.
- Sähköposti lähtee automaattisesti, jos sähköpostipalvelin on asetettu;
  muuten se odottaa **Tehtävät**-sivulla valmiiksi kirjoitettuna: *Avaa
  sähköpostissa* → lähetä → *Lähetin sen*.
- Ketju pysähtyy itsestään, kun puhelu päättyy bookkaukseen, "ei kiinnosta",
  "ei saa soittaa" tai "on jo asiakas".

## Bookkaukset

Kaikki sovitut tapaamiset. Vaihda tila (Vahvistettu / Pidetty / Peruttu / Ei
saapunut) rivillä; ✎ muokkaa aikaa, paikkaa ja arvoa; 📅 lataa
kalenteritiedoston (Outlook, Google, Apple).

## Raportit

**Päivä**: oma (tai valitun myyjän) päivä – soitot, tavoitetut, bookatut,
puheaika, vertailu edellisten 7 päivän keskiarvoon, tunneittainen jakauma.
**Jakso**: 7/30/90 päivää, kaikki soittajat.

## Agentti

Hakee yrityksiä kaupparekisteristä paikkakunnan ja toimialan mukaan, lukee
niiden verkkosivut ja ehdottaa päättäjän yhteystiedot. Mitään ei soiteta ennen
kuin hyväksyt ehdotukset – hyväksytyt menevät suoraan valittuun kampanjaan.

## Yleisimmät kysymykset

- **"Lisää jonoon" on harmaana.** Soittojono on kampanjakohtainen; luo
  kampanja samasta kohdasta (*+ Luo kampanja*) tai valitse olemassa oleva.
- **Jono on tyhjä.** Lisää yrityksiä Hausta tai listalta, tai odota
  takaisinsoittoja. "Odottaa"-luku yläpalkissa kertoo, montako tulee
  myöhemmin (kampanjan uudelleensoittoväli).
- **Henkilöllä ei ole numeroa.** Lisää numero *+ Lisää* -napista kesken
  puhelun, tai ohita valitsemalla *Vaihde / ei päättäjää* ja rastita *Opin
  uuden yhteyshenkilön*.
- **Väärä henkilö vastasi.** Valitse *Väärä numero* tai *Vaihde* ja kirjaa
  oikea henkilö lopputuloksen alle – seuraava soitto menee hänelle.
