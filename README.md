# voucher-to-yayoi-marketplace

証憑書類(領収書・請求書)から弥生会計インポートデータを作成するスキルを、
社内で共有するためのリポジトリです。

## 導入方法(各自のPCで1回だけ)

Claude Codeのチャット画面で、以下を順番に実行してください。
`<組織名>/voucher-to-yayoi-marketplace` の部分は、実際のGitHubの組織名・
リポジトリ名に置き換えてください。

```
/plugin marketplace add <組織名>/voucher-to-yayoi-marketplace
/plugin install voucher-to-yayoi@voucher-to-yayoi-marketplace
```

これで、以降どのプロジェクトフォルダで作業していても、このスキルが自動的に
使えるようになります。

## 初回のみ必要な追加セットアップ(パソコンごとに1回)

このスキルは証憑画像の宛名を自動で黒塗りする処理のためにOCR(文字認識)の
プログラムを使います。導入後、以下を1回だけ実行してください
(このときだけインターネット接続が必要です)。

```
cd <スキルのインストール先フォルダ>\scripts
python -m venv .venv
.venv\Scripts\pip install -r ../requirements.txt
```

スキルのインストール先フォルダが分からない場合は、Claude Codeのチャットで
「voucher-to-yayoiスキルの場所を教えて」と聞いてください。

## 更新方法

このリポジトリの中身を更新した後、各自のPCで以下を実行すると最新版が反映されます。

```
/plugin marketplace update voucher-to-yayoi-marketplace
```
