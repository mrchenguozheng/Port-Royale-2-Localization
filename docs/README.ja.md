# ドキュメント索引

これはプロジェクト紹介ではなく、「どの文書を見ればよいか」の索引です。
日本語版は主要なワークフローを対象にしています。一部の分析系文書は中国語のみです。

[English](README.md) · [中文](README.zh-CN.md) · [プロジェクト README](../README.ja.md)

> **対応ゲームバージョン：GOG 英語版 `1.1.2.3` のみ。** 他のバージョンは対象外です。

## プレイヤー

| 文書 | 内容 |
|---|---|
| [プレイヤーガイド](ja/user-guide.md) | zip の展開、起動、アンインストール、トラブルシューティング |

## ビルドとリリース

| 文書 | 内容 |
|---|---|
| [リリース](ja/release.md) | 言語別 zip、パッケージ構成、フォントライセンス、GitHub Releases |
| [ビルドとインストール](ja/build-and-install.md) | ワークベンチ、インストールウィザード、ビルド/デプロイ/起動 |
| [フォントと配布](ja/fonts-and-distribution.md) | Noto / 縫合フォントの再配布可否 |
| [新言語のフォント](ja/new-language-fonts.md) | 新言語に必要なフォントとツール |

## 開発

| 文書 | 内容 |
|---|---|
| [アーキテクチャ](ja/architecture.md) | レイヤー、ファイル契約、リファクタリング記録、残る境界 |
| [インジェクター](ja/injection.md) | DLL のテキストフックと起動方法 |
| [翻訳と言語パック](ja/translation-and-packs.md) | TOML 形式、`hash = text`、エディタの流れ |
| [新言語の追加](ja/new-language.md) | ゼロから言語を追加する手順 |
| [言語追加の協力フロー](ja/language-collaboration.md) | 翻訳者とメンテナーの分担・受け渡し・検証 |

## 翻訳メモ

| 文書 | 内容 |
|---|---|
| [話者ティア](ja/speaker-tiers.md) | 話者を特定できる行と推測になる行 |
| [文体提案](ja/tone-proposal.md) | 確度の高い 41 件とレビュー対象 |
| [翻訳の限界](ja/translation-limits.md) | 直せない問題、検証済み範囲、フックのトレードオフ |
| [未解決事項](ja/pending.md) | Steam、未検証の仏語版、フックオフセット |

## 中国語のみの専門文書

| 文書 | 内容 |
|---|---|
| [音声一覧](语音清单.md) / [音声マッピング](语音映射.md) | 音声ファイルと hash の対応 |
| [中国語の分かち書き](中文分词方案.md) | 中国語の分かち書きとスペース |
| [中国語テキスト変更履歴](中文文本改动对比.md) | 過去の変更対照 |
| [CSV データ](csv/README.md) | 分析・音声・レビュー・生成データ |

## 現在の契約

- ゲーム言語：`PR2Packs/locale.ini` の `language=`
- 言語パックの表示名 / GUI 言語 / 最低ランタイム：`PR2Packs/<lang>.txt` 先頭の
  `# pack-meta alias=…`, `gui=…`, `min_runtime=…`
- フォント：`fonts/<lang>/` の 4 つの TTF。`fonts/` 直下の原版は上書きしない
- ランチャー UI 翻訳：`ui/<lang>.ini`
- ランタイムバージョン：`src/injector/pr2_version.h`、リリース zip の `RUNTIME-VERSION`

詳細は [アーキテクチャ](ja/architecture.md) を参照。
