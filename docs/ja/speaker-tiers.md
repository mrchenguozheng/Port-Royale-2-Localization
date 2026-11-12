# 話者ティア（英語/フランス語原文のみに基づく）

> 自動生成：`python src/tools/analysis/speaker_audit.py`。項目ごとの明細：[speaker-audit.csv](../csv/analysis/speaker-audit.csv)。
> 判定には**英語**と**フランス語**の原文のみを使います。日本語は我々自身の翻訳であり、それを使って話者を推測するのは循環論法になるため、対象外とします。

## ティアの定義

| ティア | 意味 | 件数 |
|---|---|---|
| **A — 確定** | テキストが身元を直接示している：署名、自称、肩書きタグ | 6 |
| **B — 推測可能** | 内容から話者の役割やプレイヤーとの関係を推測できる | 668 |
| **C — 汎用** | 一人称または命令形のみで、人物の手がかりがない | 2284 |
| **N — 話者なし** | システム UI、三人称のイベントナレーション | 401 |
| **非テキスト** | ラベル/記号、デバッグ文字列、予約項目。話者判定の対象外 | 189 |
| 合計 | | 3548 |

> 話者判定は**3359 件の台詞**だけを対象に行います。残りの 189 件は非テキストであり、下に別途掲載します。

## 以前の版が雑に見えた理由

| 問題 | 旧ルール | 現行ルール |
|---|---|---|
| 「親族に言及している」を「話者が親族である」と扱っていた | `my wife` / `my daughter` が現れるだけでティア A と判定していたため、`While you are looting the town, a young woman comes running up…` のようなナレーションも親族として数えられていた | ティア B の「家族/恋人」カテゴリに変更し、**推測可能**な関係を示すだけにした。文法上の人称は別途 `person` 列で示す |
| 署名ルールが本文に一致していた | `viceroy of %1` を全文検索していたため、イベント通知 `The viceroy of %1 has moved to %2. Governor…` が「手紙の署名」と判定されていた | ルールは**末尾 90 文字**以内でのみ署名を探し、テキストが十分に長いことも要求する |
| CSV に古い日本語列が残っていた | `ja` 列が混在し、表現の変更後に同期されていなかった（`総督代理` のままだった） | 日本語列を削除し、英語とフランス語の 2 列に置き換えた（フランス語ももう 1 つの正となる原文） |
| 検証できる根拠がなかった | 中国語の 1 行の説明だけだった | `rule`（A1/A2/A3/N1/N2/B/C）と `person`（一人称/三人称/命令形/なし）を追加した |

## カテゴリ分布

| カテゴリ | 件数 |
|---|---|
| 署名 | 3 |
| 自称 | 1 |
| 肩書きタグ | 2 |
| 財務官/貸付 | 27 |
| 家族/恋人 | 39 |
| 酒場/酔漢 | 33 |
| 海賊/私掠船 | 153 |
| 役人/公務 | 126 |
| 商人/交易 | 276 |
| チュートリアル/ガイド | 14 |
| イベントナレーション | 257 |
| システム UI | 144 |
| 汎用 — 一人称 | 225 |
| 汎用 — 命令形 | 84 |
| 汎用 — なし | 1975 |

## テンプレートファミリー（C ティアのグルーピング。3 件以上で 1 ファミリー）

ファミリー内の項目は、語句だけが異なる**同一のテンプレート**です。話者が同じなので、語調も揃えるべきです。各ファミリーには「代表」を 1 件（ファミリー内で最も短い項目）選び、残りを「メンバー」としています。

| ファミリー（冒頭語） | 件数 | 代表ハッシュ | 代表の英語原文 |
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

## 非テキスト（判定対象外、189 件）

| 種類 | 件数 | 例 |
|---|---|---|
| ラベル/記号 | 129 | `%1 / %2`、`.`、`+ %1` |
| 予約項目 | 34 | `QA`、`scenario004 - @I$Idx$`、`OK` |
| デバッグ | 26 | `IDM_CONTEST_01…G_01_HDR`、`IDM_CONTEST_01…_03_TEXT`、`IDM_CONTEST_01…G_02_HDR` |

## ティア A：テキスト自体が身元を示す（6 件）

| ハッシュ | カテゴリ | ルール | 英語原文 |
|---|---|---|---|
| `0xed88c9e3` | 署名 | A1 | %1,<n><n>A loan of %2 was due on %3. The sum was collected today.<n><n>The treasurer of %4 |
| `0x03fb5c6a` | 肩書きタグ | A2 | <n><n>%1, viceroy of %2 |
| `0x101f99b7` | 署名 | A1 | %1,<n><n>I have sent you the sum of %2 gold coins today. My debt with you is therefore settled.<n><n>The Treas |
| `0x2ee7d67a` | 肩書きタグ | A2 | Viceroy of %1 |
| `0x2ef8f665` | 署名 | A1 | Welcome to %1,<n><n>I'd like to give you some words of advice to enable you to find your way in the region aro |
| `0x30bb44fd` | 自称 | A3 | Please pull up a stool, @A$USER$. My name is @N$OwnerName$ and I have an important matter to discuss with you. |

## ティア B のサンプル（各カテゴリ 3 件）

### 財務官/貸付（27 件）

- `0xce9ee62e`（なし）
  - EN: Grant loan
  - FR: Proposer un prêt
- `0xd4cd0f41`（なし）
  - EN: Although there were no white slaves in North and Central America, there were plenty of Europeans who found themselves wo
  - FR: Bien qu'il n'y ait pas eu d'esclaves blancs en Amérique du Nord ou en Amérique Centrale, de nombreux Européens travailla
- `0xd4cd0f42`（なし）
  - EN: As the American colonies flourished, so too did the trade across the Atlantic Ocean. Great Britain, the most powerful ma
  - FR: Les colonies américaines allaient florissantes, tout comme le commerce atlantique. La Grande Bretagne, qui était la nati

### 家族/恋人（39 件）

- `0xcb2b0709`（一人称）
  - EN: What a calamity! Have you visited @F$WifeName$ yet today? You can spare yourself the trouble, for she has gone. Look, I
  - FR: Quelle calamité ! Avez-vous déjà vu @F$WifeName$ aujourd'hui ? Epargnez-vous ce trajet, elle n'est pas là. Regardez, j'a
- `0xcb2b070a`（一人称）
  - EN: Disaster has struck and it appears to me that you are in the thick of it. My daughter has been abducted by pirates, but
  - FR: Le malheur frappe et il me semble que vous êtes au cœur de la tempête. Ma fille, kidnappée par des pirates. Un message q
- `0xcb2b070b`（一人称）
  - EN: Ha! My daughter, and your wife, has eloped with one of my officers of the town guard! I might have guessed! Now they are
  - FR: Ha ! Ma fille, votre épouse, enfuie avec un des officiers de ma garde ! J'aurai dû m'en douter ! Ils ont disparu tous le

### 酒場/酔漢（33 件）

- `0xc58b0f44`（一人称）
  - EN: Thank you for doing me this favor.<n><n>Now to our agreement. The old captain is called @N$TeacherName$ and he has retir
  - FR: Merci de m'avoir fait cette faveur.<n><n>Maintenant, notre contrat. Le vieux capitaine s'appelle @N$TeacherName$ et il s
- `0xc974f968`（一人称）
  - EN: Should I sign on to this convoy? The previous captain will then retire to the inn.
  - FR: Est-ce que je prends la tête de ce convoi ? Le capitaine précédent se retirera alors à l'auberge.
- `0xd3ac64cc`（一人称）
  - EN: I’m sure you also trade in rum? I can tell you something about that.
  - FR: Je suis certain que vous faites commerce du rhum ? Je dois vous en dire plus à ce sujet.

### 海賊/私掠船（153 件）

- `0xc58b0f43`（一人称）
  - EN: There you are again, and I see you’ve succeeded.<n><n>So I must keep to my side of our agreement. You will find Master @
  - FR: Ah, vous revoilà, et je vois que vous avez réussi.<n><n>Je respecterai donc ma part du contrat. Vous trouverez le Maître
- `0xc6202673`（一人称）
  - EN: I am therefore assigning you the mission of capturing a colonial town belonging to %2 by %1.    The town must not be the
  - FR: En conséquence, je vous confie la mission de capturer une ville coloniale appartenant à %2 d'ici au %1. La ville ne doit
- `0xc6362ac4`（一人称）
  - EN: Your mission is to capture any town belonging to %2 by %1.<n>To avoid any problems with the other nations, I will issue
  - FR: Votre mission consiste à capturer une ville appartenant à %2 avant le %1.<n>Pour éviter tout problème avec les nations n

### 役人/公務（126 件）

- `0xc6202672`（一人称）
  - EN: I am therefore assigning you the mission of capturing a colonial town belonging to %2 by %1.    The town must not be the
  - FR: En conséquence, je vous confie la mission de capturer une ville coloniale appartenant à %2 d'ici au %1. La ville ne doit
- `0xc772b82b`（なし）
  - EN: New governor in %1
  - FR: Nouveau gouverneur à %1
- `0xc80380bd`（なし）
  - EN: Governor’s palace
  - FR: Palais du gouverneur

### 商人/交易（276 件）

- `0xc46f793a`（一人称）
  - EN: Thank you for the @g$TotalPrice$. Meet me at the market and I will give you the goods.
  - FR: Merci pour les @g$TotalPrice$. Retrouvez-moi au marché pour que je vous y donne les marchandises.
- `0xc558e134`（なし）
  - EN: If you want as many traders as possible to visit your town, you should simply not supply your town with certain goods. Y
  - FR: Si vous voulez voir autant de marchands venir dans votre ville que possible, vous devriez ne pas ravitailler du tout la
- `0xc5d1c61b`（なし）
  - EN: Marketing Director
  - FR: Directeur du marketing

### チュートリアル/ガイド（14 件）

- `0xc6362ac3`（なし）
  - EN: So be it.<n>Your mission is to capture any town belonging to  %2 by %1.
  - FR: Qu'il en soit ainsi.<n>Votre mission consiste à capturer une ville appartenant à %2 d'ici le %1.
- `0xcf597142`（なし）
  - EN: You should be able to find him there in the next couple of months.
  - FR: Vous pourrez le trouver ici dans les prochains mois.
- `0xe3e33a30`（一人称）
  - EN: Let %1 be your new town. You can now enter it just like any other town to erect buildings and set up businesses there.<n
  - FR: Faites de %1 votre nouveau port d'attache. Vous pouvez y venir à votre guise pour y construire des bâtiments et mettre s

## 制約

- ルールはヒューリスティックです。1 つのテキストが複数のカテゴリに一致し得るため、優先度が最も高い一致を採用します。
- ティア B は「役割を推測できる」という意味にすぎず、どの NPC なのかまでは特定しません。
- 汎用の依頼・感謝・報酬の文言は複数のキャラクターで使い回されるため、話者を確定できません。
- 実際の話者を取得するには、エンジンの対話構造を解析する必要があります（言語パックには含まれていません）。

---

関連文書：[文体提案](tone-proposal.md) · [翻訳と言語パック](translation-and-packs.md)
