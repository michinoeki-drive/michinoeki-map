# 🛣️ 道の駅スタンプラリー

スマホのGPSで**現在地から近い順**に全国の道の駅を並べ、**半径100m以内**に近づくとスタンプが押せるWebアプリです。GitHub Pagesにそのまま置くだけで動きます。

## 📦 ファイル構成

```
index.html            ← アプリ本体（HTML/CSS/JS すべて入り）
stations.json         ← 全国1,231駅のデータ（緯度経度・所在地・HP・施設情報）
stations_with_coords.csv ← 参考用のCSV版
README.md             ← このファイル
```

**この2ファイル（index.html と stations.json）を GitHub リポジトリのルートに置くだけ**で公開できます。

---

## 🚀 GitHub Pages への設置手順

1. 既存のリポジトリを開く（`ユーザー名.github.io` など）
2. 古い `index.html` を削除して、この `index.html` と `stations.json` をアップロード
3. コミット → プッシュ
4. スマホで `https://ユーザー名.github.io/リポジトリ名/` を開く
5. 位置情報の利用を「許可」してください

これだけで**localStorageに保存する形（端末ローカル）で動きます**。機種変で消えないようにするには、下のFirebase設定を追加してください。

---

## ☁️ Firebase 設定（機種変でも消えないようにする）

「機種をまたいでスタンプ履歴を残す」ため、無料の Firebase Firestore に保存します。**設定しなくてもアプリは動きます**（そのぶん端末内保存になります）。

### 1. Firebase プロジェクトを作る（無料）

1. [Firebase Console](https://console.firebase.google.com/) にアクセス
2. 「プロジェクトを追加」→ 適当な名前（例：`michinoeki-stamp`）
3. Google Analytics は不要なのでOFFでOK

### 2. Firestore Database を有効化

1. 左メニュー「構築」→「Firestore Database」
2. 「データベースの作成」→**本番モードで開始**
3. リージョンは `asia-northeast1（東京）` を選択
4. 「ルール」タブで下のルールに貼り替えて「公開」：

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // ログイン中のユーザーは自分のデータだけ読み書きできる
    match /users/{uid} {
      allow read, write: if request.auth != null && request.auth.uid == uid;
    }
  }
}
```

### 3. 匿名認証を有効化

1. 左メニュー「構築」→「Authentication」→「始める」
2. 「Sign-in method」タブ →「匿名」を有効化して保存

### 4. Web アプリを登録して設定値をコピー

1. プロジェクトのトップ画面で `</>`（ウェブアプリ追加）をクリック
2. 適当なニックネームで登録（Firebase Hosting はチェック不要）
3. 表示される `firebaseConfig` の中身をコピー

### 5. index.html に貼り付ける

`index.html` の以下の部分（60行目あたり）を、コピーした値で書き換えてください：

```javascript
const FIREBASE_CONFIG = {
  apiKey: "YOUR_API_KEY",
  authDomain: "YOUR_PROJECT.firebaseapp.com",
  projectId: "YOUR_PROJECT",
  storageBucket: "YOUR_PROJECT.appspot.com",
  messagingSenderId: "000000000000",
  appId: "1:000000000000:web:xxxxxxxxxxxxxxxx"
};
```

書き換えて GitHub にプッシュすれば完了です。次回アクセスから自動でクラウド同期されます。

### 機種変時の引き継ぎ

同じ端末は自動で同じUIDで復元されますが、機種変時は「📥 スタンプ履歴をJSONで書き出す」で旧端末からエクスポート → 新端末で「📤 JSONから読み込む」で移行できます。

---

## 📱 使い方

### 3つのタブ

| タブ | できること |
|---|---|
| 📋 **近い順** | 現在地から近い順に道の駅を並べる。未訪問→訪問済の順。検索・フィルタ可能 |
| 🗺️ **地図** | 全1,231駅を地図上にプロット（灰＝未訪問、緑＝訪問済、青＝現在地） |
| 📊 **進捗** | 全国制覇率と都道府県別の完成度を可視化。エクスポート／リセットもここ |

### スタンプの押し方

1. 道の駅の**半径100m以内**に入る
2. リストで該当駅がオレンジ色に光る（🎯マーク）
3. タップして「🎯 スタンプを押す」を押す
4. 完了！ 訪問済になって緑のチェックが付きます

近づいていない状態では**ボタンが灰色でグレーアウト**します（GPS 誤差にも寛容にしたい場合は `index.html` 内の `STAMP_RADIUS_M = 100` を `300` などに変更してください）。

---

## 🗄️ データの出典と精度

- **道の駅リスト（1,231駅）**：ユーザー提供の `list.csv`（全国「道の駅」連絡会 由来）
- **緯度経度**：
  - **1,166駅**：[国土数値情報「道の駅データ」（P35-18）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P35.html)（国土交通省、2019年基準）
  - **46駅**：[Nominatim / OpenStreetMap](https://nominatim.org/) でジオコーディング（2019年以降の新規開業駅）
  - **19駅**：所在市町村役場の座標で手動補完（駅名が特殊で自動ジオコード不可）

`H30年（2018年）12月末までに登録された全国の道の駅の位置` は国土数値情報のデータが最も精確（誤差 25m 以内）です。それ以降の駅は誤差が最大数百m〜1km程度になる場合がありますが、「近い順」表示には十分な精度です。

もし特定の駅の位置が明らかにズレていたら、`stations.json` の該当駅の `lat` / `lon` を Google Maps 等で調べた正確な値に書き換えてください。

## 🔧 データを更新したいとき

新しい道の駅が登録されたら、`stations.json` の `stations` 配列に以下のように1件追加するだけでOKです：

```json
{
  "id": "○○県_駅名",
  "pref": "○○県",
  "name": "駅名",
  "touroku": "第XX回",
  "year": "R7.4",
  "addr": "○○市",
  "hp": "https://...",
  "lat": 35.12345,
  "lon": 139.12345
}
```

---

## 🧰 ライセンス

- 道の駅位置データ：国土数値情報（国土交通省、非商用利用可）
- 地図タイル：© OpenStreetMap contributors（[ODbL](https://www.openstreetmap.org/copyright)）
- アプリコード：ご自由にどうぞ
