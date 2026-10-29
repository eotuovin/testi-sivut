/** Ready-made sequences in plain Finnish. Picked when creating a new sequence;
 *  every text is editable afterwards. Variables: {{etunimi}} {{nimi}} {{yritys}}
 *  {{paikkakunta}} {{titteli}} {{myyja}} {{tuote}}. */
import type { SequenceStep } from './api/types'

export interface SequenceTemplate {
  id: string
  name: string
  description: string
  steps: SequenceStep[]
}

const sig = '\n\nTerveisin\n{{myyja}}\nMuutto365'

export const SEQUENCE_TEMPLATES: SequenceTemplate[] = [
  {
    id: 'avora',
    name: 'Avora – uudet yritykset',
    description: 'Vasta perustetuille osakeyhtiöille. Soitto ensin, lyhyet meilit ihmiseltä ihmiselle, ei tarjouksia. 20 päivää.',
    steps: [
      { kind: 'call', delay_days: 0, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 1, delay_hours: 0, title: 'Soittelin – yksi asia', body: 'Hei {{etunimi}},\n\nyritin tavoittaa puhelimella, osuin varmaan kiireeseen. Asia lyhyesti: autetaan uusia yrityksiä {{paikkakunta}}ssa saamaan varaukset, asiakastiedot ja laskutus yhteen paikkaan – ja laitetaan se pystyyn teidän puolesta.\n\nSoitan torstaina uudestaan. Jos ajankohta on huono, vastaa vaan "ei nyt", niin en häiritse.\n\n{{myyja}}\nMuutto365 / Avora' },
      { kind: 'call', delay_days: 3, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 4, delay_hours: 0, title: 'Miltä se näyttäis {{yritys}}lla', body: 'Hei {{etunimi}},\n\nettä tiedät mistä puhun: 15 minuutissa näytän Teamsissa, miten asiakas varaa ajan teidän sivulta, miten se menee kalenteriin ja asiakasrekisteriin ilman että kukaan kirjoittaa mitään käsin. Jos siinä ei ole järkeä teille, sanot sen ja asia on sillä selvä.\n\nEhdota aikaa, tai soitan ensi viikolla.\n\n{{myyja}}' },
      { kind: 'call', delay_days: 5, delay_hours: 0, title: null, body: null },
      { kind: 'task', delay_days: 7, delay_hours: 0, title: 'LinkedIn / Facebook: {{nimi}}, {{yritys}}', body: 'Lähetä LinkedIn-yhteyspyyntö ilman saatetekstiä, tai seuraa yrityksen Facebook-sivua. Ei viestiä. Palataan puhelimella 1–2 kk päästä (Soita uudelleen).' },
    ],
  },
  {
    id: 'yleinen',
    name: 'Yleinen B2B-esittely',
    description: 'Lyhyt meili, soitto, muistutus, toinen soitto, LinkedIn. 10 päivää.',
    steps: [
      { kind: 'email', delay_days: 0, delay_hours: 0, title: 'Lyhyt kysymys, {{yritys}}', body: 'Hei {{etunimi}},\n\nsoitan sinulle lähipäivinä yhdestä asiasta, joka on säästänyt vastaavilta yrityksiltä {{paikkakunta}}ssa muutaman tunnin viikossa. Jos joku toinen hoitaa teillä näitä, kerro kenelle kannattaa soittaa.' + sig },
      { kind: 'call', delay_days: 2, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 3, delay_hours: 0, title: 'Re: Lyhyt kysymys, {{yritys}}', body: 'Hei {{etunimi}},\n\nyritin tavoittaa puhelimella. Riittäisikö 15 minuuttia ensi viikolla, niin näytän miten tämä toimii teillä? Ehdota aikaa, niin laitan kalenterikutsun.' + sig },
      { kind: 'call', delay_days: 4, delay_hours: 0, title: null, body: null },
      { kind: 'task', delay_days: 1, delay_hours: 0, title: 'LinkedIn-yhteyspyyntö: {{nimi}}', body: 'Lähetä yhteyspyyntö ilman saatetekstiä. Jos hyväksyy, lyhyt viesti: "Kiitos, soittelen vielä kun ehdit."' },
    ],
  },
  {
    id: 'ravintolat',
    name: 'Ravintolat ja kahvilat',
    description: 'Soitot iltapäivällä lounasruuhkan jälkeen. Meilit lyhyitä, puhutellaan omistajaa.',
    steps: [
      { kind: 'call', delay_days: 0, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 1, delay_hours: 0, title: '{{yritys}} – 2 minuuttia', body: 'Moi {{etunimi}},\n\nkävin soittamassa, mutta osuin varmaan kiireeseen. Asia lyhyesti: autamme ravintoloita {{paikkakunta}}ssa hoitamaan {{tuote}} niin, ettei se vie sinun aikaasi. Soitan uudestaan iltapäivällä, tai vastaa tähän milloin sopii.' + sig },
      { kind: 'call', delay_days: 2, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 5, delay_hours: 0, title: 'Viimeinen yritys, {{etunimi}}', body: 'Hei {{etunimi}},\n\nen halua häiritä turhaan. Jos tämä ei ole nyt ajankohtaista, ei mitään – laita vaikka "ei nyt", niin palaan keväällä. Jos taas kiinnostaa, 15 minuutin esittely riittää.' + sig },
    ],
  },
  {
    id: 'rakennus',
    name: 'Rakennus ja urakointi',
    description: 'Työmaapäälliköt eivät lue meilejä työpäivän aikana – soitot aamulla, meilit illalla.',
    steps: [
      { kind: 'call', delay_days: 0, delay_hours: 0, title: null, body: null },
      { kind: 'call', delay_days: 1, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 1, delay_hours: 0, title: '{{yritys}} – soittelin pariin otteeseen', body: 'Hei {{etunimi}},\n\nyritin tavoittaa puhelimella. Kyse on {{tuote}} – ei vaadi teiltä mitään ennen kuin olette nähneet sen toiminnassa. Mihin aikaan päivästä sinut tavoittaa parhaiten?' + sig },
      { kind: 'call', delay_days: 3, delay_hours: 0, title: null, body: null },
      { kind: 'task', delay_days: 2, delay_hours: 0, title: 'Tarkista toinen päättäjä: {{yritys}}', body: 'Katso yrityksen sivuilta tai Haku → Henkilöt, löytyykö toimitusjohtaja tai työpäällikkö. Lisää henkilö ja soita hänelle.' },
    ],
  },
  {
    id: 'asiantuntijat',
    name: 'Tilitoimistot ja asiantuntijat',
    description: 'Meili ensin, sitten soitto – asiantuntijat lukevat sähköpostin ja arvostavat että olet perehtynyt.',
    steps: [
      { kind: 'email', delay_days: 0, delay_hours: 0, title: '{{yritys}}: yksi konkreettinen idea', body: 'Hei {{etunimi}},\n\nkatsoin {{yritys}}n sivuja ja mieleen tuli yksi asia, jolla vastaavat toimistot ovat säästäneet rutiinityötä. Soitan sinulle torstaina ja kerron sen kahdessa minuutissa – jos aika ei sovi, ehdota toista.' + sig },
      { kind: 'call', delay_days: 2, delay_hours: 0, title: null, body: null },
      { kind: 'email', delay_days: 4, delay_hours: 0, title: 'Re: {{yritys}}: yksi konkreettinen idea', body: 'Hei {{etunimi}},\n\nlyhyesti: {{tuote}}. Jos haluat nähdä sen käytännössä, 20 minuutin Teams riittää. Ehdota aikaa tai sano, jos ei ole nyt ajankohtaista.' + sig },
      { kind: 'call', delay_days: 3, delay_hours: 0, title: null, body: null },
    ],
  },
  {
    id: 'lammittely',
    name: 'Lämmittely vanhoille liideille',
    description: 'Yrityksille, jotka sanoivat "ei nyt" 2–3 kk sitten. Yksi meili, yksi soitto.',
    steps: [
      { kind: 'email', delay_days: 0, delay_hours: 0, title: 'Palataan asiaan, {{etunimi}}', body: 'Hei {{etunimi}},\n\njuttelimme jokin aika sitten ja silloin ei ollut oikea hetki. Tilanne on saattanut muuttua, joten kysyn kerran: olisiko nyt parempi aika katsoa {{tuote}} läpi? Soitan ensi viikolla, ellet vastaa tähän ennen sitä.' + sig },
      { kind: 'call', delay_days: 5, delay_hours: 0, title: null, body: null },
    ],
  },
]
