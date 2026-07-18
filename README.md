# ラベル作成ツール

商品マスター（Google Sheets）から商品を選び、ラベルPDFを作って Google Drive に保存する Web ツールです。

- 1商品につき1ファイル
- 1ファイル = ラベルシート1枚分（44面すべて同じ商品）
- 同じ名前のファイルがある場合は上書き（作り直した最新のものが正しいため）

---

## セットアップ

### 1. GitHubにリポジトリを作る

このフォルダの中身をそのまま置きます。**private リポジトリでも public でも構いません。**

```
label-app/
├── app.py                        画面と処理
├── label_gen.py                  PDF生成（検証済み）
├── requirements.txt              Pythonのライブラリ
├── packages.txt                  日本語フォント（重要）
├── .gitignore                    鍵を誤って上げないための設定
└── .streamlit/
    └── secrets.toml.example      鍵の書き方の見本
```

> `packages.txt` に `fonts-ipafont-gothic` を書いています。
> これが無いと日本語が豆腐（□□□）になります。

**JSONの鍵ファイルは絶対に置かないでください。** `.gitignore` で防いでいますが、念のため確認を。

### 2. Streamlit Cloud に接続する

1. https://share.streamlit.io/ を開く
2. **Continue with GitHub** でサインイン
3. **Create app** → **Deploy a public app from a repo**
4. 次を指定して **Deploy**

```
Repository   : （作ったリポジトリ）
Branch       : main
Main file    : app.py
```

初回のビルドは3〜5分ほどかかります。

### 3. 鍵を登録する

デプロイ直後はエラーになります。鍵がまだ無いためです。

1. アプリ画面の右下 **Manage app** → 右上「⋮」→ **Settings** → **Secrets**
2. ダウンロードしたJSONを、下の形式に直して貼り付け
3. **Save**（自動で再起動します）

```toml
[app]
password = "社内で共有するパスワード"

[gcp_service_account]
type = "service_account"
project_id = "tsubaya-label"
private_key_id = "（JSONの private_key_id）"
private_key = """-----BEGIN PRIVATE KEY-----\nMIIE...\n-----END PRIVATE KEY-----\n"""
client_email = "label-generator@tsubaya-label.iam.gserviceaccount.com"
client_id = "（JSONの client_id）"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "（JSONの client_x509_cert_url）"
universe_domain = "googleapis.com"
```

**private_key の注意点**

- JSONでは1行に `\n` が並んでいます。**その `\n` は消さずにそのまま**にしてください
- 全体を `"""` （三重引用符）で囲みます

### 4. 動作確認

アプリを開くとパスワードを聞かれます。
`[app] password` に設定したものを入力し、商品一覧が出れば成功です。

---

## セキュリティについて

Streamlit Cloud の無料プランには、アクセス制限の機能がありません。
URLは誰でも開ける状態になるため、次の対策を入れてあります。

- **パスワード認証**：入力するまで商品データを読み込みません
- **検索避け**：`noindex` を指定し、検索エンジンに載らないようにしています

パスワードは Secrets の `[app] password` で変更できます。
変更したい場合は Secrets を編集して Save するだけです（再デプロイ不要）。

---

## 設定値

すでに `app.py` に書き込んであります。変更する場合はここを直します。

| 項目 | 値 |
|---|---|
| スプレッドシートID | `1qS6mU5pnVN40KdF-6LcSve5axrrzEwvx2pJKn0jBC30` |
| 保存先フォルダID | `1Se_ML_NoAKZgTBRxPpmAyAtZzFBEE9G4` |
| 読むシート名 | `商品マスター` |

サービスアカウント `label-generator@tsubaya-label.iam.gserviceaccount.com` に、
次の2つが共有されている必要があります。

- 商品マスター（スプレッドシート）→ **閲覧者**
- 保存先フォルダ → **編集者**

---

## 使い方（スタッフ向け）

1. 絞り込み（仕入先・鋼材・種類・和洋・柄の素材）や検索で商品を探す
2. 一覧の「選択」にチェックを入れる（いくつでも可）
3. **［PDFを作成］** を押す
4. 表示されたリンクからPDFを開いて印刷する

### 印刷のとき

- 倍率は **100%（等倍）**。「用紙サイズに合わせる」は **オフ**
- 手差しトレイ・厚紙モード
- 同じラベルが何枚も必要なときは、印刷画面で **部数** を増やす

### ラベル

- エーワン **28388**（A4 44面 / 48.3 × 25.4mm / レーザー用・四辺余白付）
- 余ったシートは保管して、次回同じ商品が入ったときに使えます

---

## 困ったとき

**日本語が □□□ になる**
`packages.txt` に `fonts-ipafont-gothic` があるか確認してください。

**「商品マスターを読み込めませんでした」と出る**
- サービスアカウントにスプレッドシートが共有されているか
- Secrets の `private_key` の `\n` が消えていないか

**PDFの保存でエラーになる**
保存先フォルダがサービスアカウントに **編集者** で共有されているか確認してください。

**パスワードを変えたい**
Streamlit Cloud の Settings → Secrets で `[app] password` を書き換えて Save してください。

**商品マスターを直したのに反映されない**
左のサイドバーの **［最新のデータを読み込む］** を押してください。
（5分間はデータを覚えているため）

**印刷位置がずれる**
手差し給紙では1mm前後ずれることがありますが、
ラベルの内側に2.5mmの余白を取ってあるため、多少ずれても文字は切れません。
大きくずれる場合は、倍率が100%になっているか確認してください。
