# Earned Club Implementation Plan

## Cil

Prevest Earned Club z jednoducheho verified leaderboardu na uctovou a progresni platformu, ale zachovat soucasny mysteriozni dark rezim: tmave pozadi, prusvitne panely, zlaty/oranzovy akcent, hutnou typografii a pocit verejneho vykonoveho klubu.

Tento plan vychazi z:

- `DEPLOYMENT_PLAN.md`
- `docs/plans/FEATURE_EXPANSION_SPEC.md`
- aktualniho Django kodu v `main/models.py`, `main/views.py`, `main/templates/` a `main/tests.py`

## Zakladni pravidla implementace

1. Manual verification zustava hlavni zdroj duvery.
2. Verejny leaderboard dal pocita jen overene vysledky.
3. Legacy anonymni submissions musi zustat funkcni.
4. Nove ucty a profily se pridavaji vedle existujiciho flow, ne jako tvrda bariera.
5. UI navazuje na soucasny dark system v `base.html`; zadny svetly redesign.
6. Kazda faze ma vlastni migrace a testy.

## UI a dark rezim

Soucasny vizualni jazyk je dobry zaklad a ma se rozsirit, ne prepsat.

Zachovat:

- `--bg`, `--bg-soft`, `--panel`, `--panel-strong`, `--line`, `--text`, `--muted`
- zlaty akcent `--accent` a oranzovy sekundarni akcent `--accent-2`
- prusvitne panely s jemnym borderem
- sticky tmavy topbar
- velke nadpisy pres `Archivo`
- text pres `Source Sans 3`
- CTA tlacitka ve stylu `btn-main` a `btn-secondary`

Pridat jen opatrne:

- `.auth-card` pro login/register, stylove stejny jako `.card-dark`
- `.profile-header` pro athlete profil
- `.metric-card` pro dashboard metriky
- `.progress-chart` pro graf progresu
- `.status-pill` pro pending/verified/rejected
- `.rank-card-preview` pro shareable rank card

Nepridavat:

- svetle sekce
- bile admin-like formulare
- novy barevny system
- dekorativni gradientove pozadi mimo existujici atmosferu
- marketingovou landing page misto pouzitelnych obrazovek

## Faze 0: Stabilizace pred rozsirenim

### Cil

Srovnat aktualni zaklad, aby dalsi zmeny nestavely na rozjetych detailech.

### Kroky

1. Spustit aktualni testy.
2. Overit migrace proti lokalnimu SQLite.
3. Zkontrolovat, ze `Submission` odpovida poslednim migracim.
4. Opravit calculator thresholds tak, aby odpovidaly `RANK_TIERS`:
   - Beginner: `0-19`
   - Intermediate: `20-39`
   - Advanced: `40-59`
   - Elite: `60-79`
   - Earned Legend: `80+`
5. Pridat testy pro hranice rank tieru.
6. Pripravit helper pro odhad pozice neovereneho submissionu na verified leaderboardu.

### Poznamka k motivaci po submitu

Po odeslani vysledku zobrazit zpravu typu:

`Submission received. If verified, this result would currently rank #X on the verified leaderboard.`

Pocitat ji vlozenim noveho reps skore do aktualnich overenych vysledku.

## Faze 1: Ucty, profily a linkovane submissions

### Cil

Pridat registraci, login/logout, verejne profily a propojit nove submissions s uzivateli bez rozbiti anonymniho flow.

### Modely

Pridat `Profile`:

- `user = OneToOneField(User)`
- `display_name`
- `slug`
- `profile_photo`
- `bio`
- `current_rank`
- `personal_best_reps`
- `created_at`
- `updated_at`

Rozsirit `Submission`:

- `user = ForeignKey(User, null=True, blank=True, on_delete=SET_NULL)`
- `email = EmailField(blank=True)`
- doporucene `status = CharField(choices=pending/verified/rejected, default=pending)`

Kompatibilita:

- bud docasne ponechat `verified`
- nebo migrovat na `status` a pridat helper `is_verified`
- doporuceni: pridat `status` nyni, ale udrzet `verified` behem prechodne faze, aby se snizilo riziko regresi

### Views a routy

Pridat:

- `/register/`
- `/login/`
- `/logout/`
- `/dashboard/`
- `/athlete/<slug>/`

Upravit:

- `/challenge/`
  - logged-in: jmeno a email brat z profilu/uzivatele
  - logged-out: vyzadovat name + email + reps, video link muze byt podle spec volitelny
  - blokovat dalsi pending submission

### Templates

Pridat:

- `register.html`
- `login.html`
- `dashboard.html` zatim zaklad
- `athlete_profile.html`

Upravit:

- `base.html` auth-aware navigace:
  - verejne: Home, Challenge, Leaderboard, Profiles
  - logged-out: Login, Register
  - logged-in: Dashboard, My Profile, Logout
  - Calculators nechat mimo hlavni nav, linkovat z homepage/leaderboardu

### Testy

Pridat testy:

- registrace vytvori `User` i `Profile`
- slug profilu je unikatni
- logged-in submission se propoji s userem
- anonymni submission stale funguje
- leaderboard stale ukazuje pouze overene
- duplicitni pending submission je zablokovany
- athlete profil ukazuje jen overene submissions

## Faze 2: Dashboard a calculator

### Cil

Udelat z uctu duvod se vracet: progres, PR, pending stav a jasny dalsi cil.

### Dashboard metriky

Pocitat jen z overenych submissions:

- current verified PR
- all-time PR
- current rank
- rank movement placeholder
- total verified submissions
- total pending submissions
- weeks active
- current verified-submission streak

Pending submissions zobrazit zvlast, bez zapocteni do vykonovych statistik.

### Progress graph

MVP:

- data pripravit ve view jako JSON-safe list
- vykreslit jednoduchy SVG/HTML line chart nebo maly inline JS graf
- drzet dark styling: tmave pozadi grafu, zlata linie, tlumene osy

### Calculator

Upravit `calculators.html`:

- pouzit `RANK_TIERS` jako zdroj pravdy
- zobrazit current tier
- reps needed to Elite (`60`)
- reps needed to Earned Legend (`80`)
- estimated weeks podle volitelneho weekly improvement

### Testy

Pridat:

- dashboard vyzaduje login
- dashboard ignoruje unverified/pending submissions
- calculator vraci spravne hranice tieru
- progress data obsahuji jen verified submissions

## Faze 3: Challenges

### Cil

Prevest `/challenge/` z obecneho formulare na aktivni soutezni kontext, ale zachovat jednoduchost submitu.

### Modely

Pridat `Challenge`:

- `name`
- `slug`
- `description`
- `challenge_type`
- `start_date`
- `end_date`
- `active`
- `created_at`
- `updated_at`

Rozsirit `Submission`:

- `challenge = ForeignKey(Challenge, null=True, blank=True, on_delete=SET_NULL)`

### Views a routy

Pridat:

- `/challenges/archive/`
- `/challenge/<slug>/`

Upravit:

- `/challenge/` zobrazi aktivni challenge
- challenge detail zobrazi pravidla, formular a verified leaderboard pro konkretni challenge

### Testy

- aktivni challenge se zobrazi na `/challenge/`
- challenge leaderboard pocita jen verified
- pending submission se neobjevi jako vitez
- legacy submission bez challenge dal muze existovat

## Faze 4: Rank cards a badges

### Cil

Pridat motivacni retencni vrstvu bez slozite infrastruktury.

### Rank card

Pridat `/rank-card/` pro logged-in uzivatele.

MVP:

- HTML/CSS preview v pomeru `1080x1920`
- obsah:
  - display name
  - verified rank
  - tier
  - verified PR reps
  - Earned Club branding
- zadne zapocteni pending vysledku

Dark styl:

- pouzit stejne barvy a typografii
- karta muze byt dramatictejsi, ale porad v ramci existujiciho systemu
- preview nesmi vypadat jako oddeleny svetly social template

### Badges

Pridat:

- `Badge`
- `UserBadge`

MVP badges:

- First Submission
- Top 10
- Elite Athlete
- Weekly Winner
- 5 Submission Streak

Awarding:

- jen po overeni submissionu
- MVP pres admin action nebo management command
- signaly az pozdeji, pokud bude potreba

### Testy

- rank card ignoruje pending data
- badge se neudeli za pending submission
- Elite Athlete badge se udeli po verified score `60+`
- First Submission badge se udeli po prvni verified submission

## Faze 5: Produkcni dotazeni

### Cil

Pripravit zmeny pro Render + Supabase bez prekvapeni.

### Kroky

1. Spustit cely test suite.
2. Overit migrace od ciste DB.
3. Overit migrace nad existujici SQLite DB.
4. Overit `collectstatic`.
5. Zkontrolovat `DEBUG=False` flow.
6. Zkontrolovat admin pro nove modely.
7. Pridat README sekci pro nove routes a verification workflow.

## Doporucene poradi PR/commitu

1. Stabilizace rank tieru, calculatoru a testu.
2. `Profile` model + registrace/login/logout.
3. Submission user/email/status migrace + pending guard.
4. Athlete profiles + auth-aware navigation.
5. Dashboard metriky + graph.
6. Challenge model + challenge routes.
7. Rank card HTML.
8. Badge modely + admin/management awarding.
9. Produkcni cleanup a README.

## Rizika

### Status migrace

Prechod z `verified` booleanu na `status` je nejcitlivejsi cast.

Doporuceni:

- nejdriv pridat `status`
- datovou migraci nastavit `verified=True -> status=verified`
- `verified=False -> status=pending`
- views postupne prepnout na helper `is_verified`
- po stabilizaci rozhodnout, jestli `verified` odstranit

### Video link

Spec rika, ze logged-out low-friction flow ma mit video link volitelny, ale soucasny model ho vyzaduje.

Doporuceni:

- pokud ma zustat credibility-first MVP, ponechat video link povinny ve Fazi 1
- pokud ma byt low-friction priorita, zmenit `video_link` na `blank=True` a UI jasne odlisit pending honor-system entry od verified proof entry

### Profily a legacy submissions

Legacy submissions nemaji usera.

Doporuceni:

- leaderboard je zobrazuje dal jako textove jmeno
- athlete profil linkovat jen tam, kde `submission.user.profile` existuje
- claim flow nechat na future fazi

## Definition of Done

Implementace je hotova, kdyz:

- registrace, login a logout funguji
- kazdy novy user ma profil
- logged-in submission je propojeny s userem
- anonymni submission stale funguje
- uzivatel nemuze mit vic aktivnich pending submissions
- leaderboard a dashboard pocitaji pouze verified vysledky
- athlete profil ukazuje pouze verified historii
- calculator pouziva stejne rank hranice jako backend
- nove stranky vizualne sedi do stavajiciho dark rezimu
- testy pokryvaji hlavni submission, ranking a auth flow
- migrace projdou na SQLite a jsou pripravene pro Supabase Postgres
