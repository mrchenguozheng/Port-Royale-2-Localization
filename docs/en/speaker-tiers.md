# Speaker Tiers (English/French Source Text Only)

> Auto-generated: `python src/tools/analysis/speaker_audit.py`. Entry-by-entry details: [speaker-audit.csv](../csv/analysis/speaker-audit.csv).
> Classification uses only the **English** and **French** source text. Japanese is our own translation; using it to infer the speaker would be circular reasoning, so it is excluded.

## Tier definitions

| Tier | Meaning | Entries |
|---|---|---|
| **A — definite** | The text directly states the identity: signature, self-identification, title tag | 6 |
| **B — inferable** | The speaker's role or relationship to the player can be inferred from the content | 668 |
| **C — generic** | First person or imperative only; no character cues | 2284 |
| **N — no speaker** | System UI, third-person event narration | 401 |
| **Non-text** | Labels/symbols, debug strings, reserved entries; excluded from speaker classification | 189 |
| Total | | 3548 |

> Speaker classification is performed only on the **3359 dialogue entries**; the remaining 189 are non-text and are listed separately below.

## Why the previous version looked messy

| Problem | Old rule | Current rule |
|---|---|---|
| Treating "mentions a relative" as "the speaker is a relative" | Any occurrence of `my wife` / `my daughter` was classified as Tier A, so narration such as `While you are looting the town, a young woman comes running up…` was also counted as a relative | Changed to the "Family/lovers" category in Tier B, which only indicates an **inferable** relationship; a separate `person` column indicates the grammatical person |
| The signature rule matched body text | A full-text search for `viceroy of %1` classified the event notice `The viceroy of %1 has moved to %2. Governor…` as a "letter signature" | The rule looks for a signature only within the **last 90 characters** and requires the text to be long enough |
| The CSV had a stale Japanese column | A `ja` column was mixed in and was not updated after wording changes (it still showed `総督代理`) | Removed the Japanese column and replaced it with two columns, English and French (French is another authoritative text) |
| No verifiable basis | Only a one-line Chinese explanation | Added `rule` (A1/A2/A3/N1/N2/B/C) and `person` (first person/third person/imperative/none) |

## Category distribution

| Category | Entries |
|---|---|
| Signature | 3 |
| Self-identification | 1 |
| Title tag | 2 |
| Treasurer/loans | 27 |
| Family/lovers | 39 |
| Tavern/drunkards | 33 |
| Pirates/privateers | 153 |
| Officials/official business | 126 |
| Merchants/trade | 276 |
| Tutorial/guidance | 14 |
| Event narration | 257 |
| System UI | 144 |
| Generic — first person | 225 |
| Generic — imperative | 84 |
| Generic — none | 1975 |

## Template families (C-tier grouping; at least 3 entries to count as a family)

Entries in a family are **the same template** with different wording: the speaker is the same, so the tone should be consistent. For each family, one "representative" is marked (the shortest entry in the family); the rest are marked "members".

| Family (opening words) | Entries | Representative hash | Representative English |
|---|---|---|---|
| `the place is` | 20 | `0x074ed221` | The place is located to the west of %1. |
| `the place lies` | 19 | `0x074ed1b1` | The place lies to the south of %1. |
| `do you want` | 15 | `0xf7b3d0f1` | Do you want to overwrite it? |
| `you have found` | 13 | `0xd2517441` | You have found the hideout. |
| `attack on a` | 13 | `0xf2073384` | Attack on a Dutch trader |
| `thank you for` | 12 | `0x0e60a698` | Thank you for your kind donation. |
| `congratulations you have` | 11 | `0x146c233b` | Congratulations! You have successfully completed each of the tasks in |
| `the position is` | 10 | `0x074ed141` | The position is located near %1. |
| `we are at` | 8 | `0xd4d24dd1` | We are at war with %1. |
| `you have not` | 8 | `0x0b2775c3` | You have not delivered the goods in time. |
| `you have defeated` | 8 | `0x30383766` | You have defeated your opponent and sunk a ship. |
| `the position lies` | 8 | `0x074ed13d` | The position lies close to %1. |
| `a local trader` | 7 | `0x2190d204` | A local trader is prepared to pay you %1 for the business. |
| `you begin your` | 7 | `0x36f07391` | You begin your career in the Dutch town of %1 in the year %2.<n><n> |
| `warehouse` | 7 | `0x081e1857` | Warehouse |

## Non-text (excluded from classification, 189 entries)

| Type | Entries | Examples |
|---|---|---|
| Labels/symbols | 129 | `%1 / %2`, `.`, `+ %1` |
| Reserved entries | 34 | `QA`, `scenario004 - @I$Idx$`, `OK` |
| Debug | 26 | `IDM_CONTEST_01…G_01_HDR`, `IDM_CONTEST_01…_03_TEXT`, `IDM_CONTEST_01…G_02_HDR` |

## Tier A: the text itself specifies the identity (6 entries)

| Hash | Category | Rule | English source |
|---|---|---|---|
| `0xed88c9e3` | Signature | A1 | %1,<n><n>A loan of %2 was due on %3. The sum was collected today.<n><n>The treasurer of %4 |
| `0x03fb5c6a` | Title tag | A2 | <n><n>%1, viceroy of %2 |
| `0x101f99b7` | Signature | A1 | %1,<n><n>I have sent you the sum of %2 gold coins today. My debt with you is therefore settled.<n><n>The Treas |
| `0x2ee7d67a` | Title tag | A2 | Viceroy of %1 |
| `0x2ef8f665` | Signature | A1 | Welcome to %1,<n><n>I'd like to give you some words of advice to enable you to find your way in the region aro |
| `0x30bb44fd` | Self-identification | A3 | Please pull up a stool, @A$USER$. My name is @N$OwnerName$ and I have an important matter to discuss with you. |

## Tier B samples (3 per category)

### Treasurer/loans (27 entries)

- `0xce9ee62e` (none)
  - EN: Grant loan
  - FR: Proposer un prêt
- `0xd4cd0f41` (none)
  - EN: Although there were no white slaves in North and Central America, there were plenty of Europeans who found themselves wo
  - FR: Bien qu'il n'y ait pas eu d'esclaves blancs en Amérique du Nord ou en Amérique Centrale, de nombreux Européens travailla
- `0xd4cd0f42` (none)
  - EN: As the American colonies flourished, so too did the trade across the Atlantic Ocean. Great Britain, the most powerful ma
  - FR: Les colonies américaines allaient florissantes, tout comme le commerce atlantique. La Grande Bretagne, qui était la nati

### Family/lovers (39 entries)

- `0xcb2b0709` (first person)
  - EN: What a calamity! Have you visited @F$WifeName$ yet today? You can spare yourself the trouble, for she has gone. Look, I
  - FR: Quelle calamité ! Avez-vous déjà vu @F$WifeName$ aujourd'hui ? Epargnez-vous ce trajet, elle n'est pas là. Regardez, j'a
- `0xcb2b070a` (first person)
  - EN: Disaster has struck and it appears to me that you are in the thick of it. My daughter has been abducted by pirates, but
  - FR: Le malheur frappe et il me semble que vous êtes au cœur de la tempête. Ma fille, kidnappée par des pirates. Un message q
- `0xcb2b070b` (first person)
  - EN: Ha! My daughter, and your wife, has eloped with one of my officers of the town guard! I might have guessed! Now they are
  - FR: Ha ! Ma fille, votre épouse, enfuie avec un des officiers de ma garde ! J'aurai dû m'en douter ! Ils ont disparu tous le

### Tavern/drunkards (33 entries)

- `0xc58b0f44` (first person)
  - EN: Thank you for doing me this favor.<n><n>Now to our agreement. The old captain is called @N$TeacherName$ and he has retir
  - FR: Merci de m'avoir fait cette faveur.<n><n>Maintenant, notre contrat. Le vieux capitaine s'appelle @N$TeacherName$ et il s
- `0xc974f968` (first person)
  - EN: Should I sign on to this convoy? The previous captain will then retire to the inn.
  - FR: Est-ce que je prends la tête de ce convoi ? Le capitaine précédent se retirera alors à l'auberge.
- `0xd3ac64cc` (first person)
  - EN: I’m sure you also trade in rum? I can tell you something about that.
  - FR: Je suis certain que vous faites commerce du rhum ? Je dois vous en dire plus à ce sujet.

### Pirates/privateers (153 entries)

- `0xc58b0f43` (first person)
  - EN: There you are again, and I see you’ve succeeded.<n><n>So I must keep to my side of our agreement. You will find Master @
  - FR: Ah, vous revoilà, et je vois que vous avez réussi.<n><n>Je respecterai donc ma part du contrat. Vous trouverez le Maître
- `0xc6202673` (first person)
  - EN: I am therefore assigning you the mission of capturing a colonial town belonging to %2 by %1.    The town must not be the
  - FR: En conséquence, je vous confie la mission de capturer une ville coloniale appartenant à %2 d'ici au %1. La ville ne doit
- `0xc6362ac4` (first person)
  - EN: Your mission is to capture any town belonging to %2 by %1.<n>To avoid any problems with the other nations, I will issue
  - FR: Votre mission consiste à capturer une ville appartenant à %2 avant le %1.<n>Pour éviter tout problème avec les nations n

### Officials/official business (126 entries)

- `0xc6202672` (first person)
  - EN: I am therefore assigning you the mission of capturing a colonial town belonging to %2 by %1.    The town must not be the
  - FR: En conséquence, je vous confie la mission de capturer une ville coloniale appartenant à %2 d'ici au %1. La ville ne doit
- `0xc772b82b` (none)
  - EN: New governor in %1
  - FR: Nouveau gouverneur à %1
- `0xc80380bd` (none)
  - EN: Governor’s palace
  - FR: Palais du gouverneur

### Merchants/trade (276 entries)

- `0xc46f793a` (first person)
  - EN: Thank you for the @g$TotalPrice$. Meet me at the market and I will give you the goods.
  - FR: Merci pour les @g$TotalPrice$. Retrouvez-moi au marché pour que je vous y donne les marchandises.
- `0xc558e134` (none)
  - EN: If you want as many traders as possible to visit your town, you should simply not supply your town with certain goods. Y
  - FR: Si vous voulez voir autant de marchands venir dans votre ville que possible, vous devriez ne pas ravitailler du tout la
- `0xc5d1c61b` (none)
  - EN: Marketing Director
  - FR: Directeur du marketing

### Tutorial/guidance (14 entries)

- `0xc6362ac3` (none)
  - EN: So be it.<n>Your mission is to capture any town belonging to  %2 by %1.
  - FR: Qu'il en soit ainsi.<n>Votre mission consiste à capturer une ville appartenant à %2 d'ici le %1.
- `0xcf597142` (none)
  - EN: You should be able to find him there in the next couple of months.
  - FR: Vous pourrez le trouver ici dans les prochains mois.
- `0xe3e33a30` (first person)
  - EN: Let %1 be your new town. You can now enter it just like any other town to erect buildings and set up businesses there.<n
  - FR: Faites de %1 votre nouveau port d'attache. Vous pouvez y venir à votre guise pour y construire des bâtiments et mettre s

## Limitations

- The rules are heuristic: one text can match several categories, and the highest-priority match is used;
- Tier B only means "the role can be inferred"; it does not determine which NPC it is;
- Generic commission/thanks/reward text is reused by several characters, so the speaker cannot be determined;
- Obtaining the actual speaker would require parsing the engine's dialogue structure (which the language pack does not contain).

---

Related docs: [Tone proposals](tone-proposal.md) · [Translations & packs](translation-and-packs.md)
