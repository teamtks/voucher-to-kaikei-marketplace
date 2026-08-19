"""確定(予定)の仕訳データ(JSON)と、その元になった証憑画像から、見比べながら
その場で訂正もできるチェック資料(単体HTMLファイル)を作成する。

入力JSONは generate_yayoi.py と同じ形式に、各明細(leg)へ以下のキーを
追加したものを使う:

    "source_image": "<黒塗り前の証憑画像のファイルパス>"

このHTMLはユーザー自身のローカル環境だけで開くファイルであり、Claudeがこの
画像を読み込むことは無いため、source_imageには黒塗り前(マスク前)の画像を
指定する想定である(黒塗りはClaudeの読み取り時に外部へ渡る情報を減らすための
処理であり、ユーザー自身がローカルで見比べる分には不要なため)。

同じ voucher_id を持つ明細は1つの証憑カードとしてまとめて表示され、
カードをクリックすると、左側にその証憑画像が表示される。

このHTMLはブラウザ上で内容を直接編集できる(勘定科目・金額・摘要など)。
「変更をJSONとして保存」ボタンを押すと、修正後の内容を同じ形式のJSONファイル
としてダウンロードできるので、そのファイルをそのまま generate_yayoi.py の
入力にすればよい。サーバー等は使わず、ブラウザ内の操作だけで完結する。

出力したHTMLは案件フォルダの中に置かれるため、そのままでは開くのにフォルダを
辿る必要がある。そこで既定では、デスクトップに「仕訳チェック資料」という
ショートカットも作成する(常に最後に生成したチェック資料を指す。過去の分は
案件フォルダから開けるので、アイコンが増え続けないように1つを使い回す)。
不要な場合は --no-desktop-shortcut を付ける。

使い方:
    python generate_review_html.py <入力JSON> <出力先.html> [--no-desktop-shortcut]
"""
import argparse
import base64
import hashlib
import html
import json
import mimetypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.desktop_shortcut import ShortcutError, create_shortcut, desktop_dir

SHORTCUT_NAME = "仕訳チェック資料.lnk"


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


def _to_data_uri(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{_guess_mime(path)};base64,{data}"


def _guess_project_folder(legs: list) -> "str | None":
    """source_imageのパスから、案件フォルダ(証憑書類/参考資料ファイルの親)を推測する。

    ブラウザのダウンロードはセキュリティ上の理由でJS側から保存先フォルダを直接
    指定できないため、保存ダイアログでどこを選べばよいかユーザーに示すために使う。
    """
    for leg in legs:
        path = leg.get("source_image", "")
        if not path:
            continue
        parent = Path(path).parent
        if parent.name in ("証憑書類", "参考資料ファイル"):
            return str(parent.parent)
        return str(parent)
    return None


# 弥生会計の税区分名は「課税区分＋税入力区分＋税率(＋インボイス区分)」の組み合わせで
# できている(公式資料「課税方式別税区分・税計算区分一覧」で確認)。本アプリは金額を
# 税込で扱うため、税入力区分は常に「込」。
#
# インボイス区分は課税仕入にのみ付く。「適格」以外は免税事業者等からの仕入に対する
# 経過措置で、控除できる割合が期間によって変わる(区分80%→区分50%→控不)。
_INVOICE_OPTIONS = [
    {"value": "適格", "label": "適格(全額控除)"},
    {"value": "区分80%", "label": "区分80%(免税事業者等・経過措置)"},
    {"value": "区分50%", "label": "区分50%(免税事業者等・経過措置)"},
    {"value": "控不", "label": "控不(控除不可)"},
]

_BUSINESS_TYPE_KANJI = {
    "1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六",
    "一": "一", "二": "二", "三": "三", "四": "四", "五": "五", "六": "六",
}


def _sales_business_type(data: dict) -> str:
    """簡易課税の事業区分(第○種事業)。本則課税なら空文字。

    簡易課税の顧問先では、売上側の税区分名に事業区分が入る
    (実データで「課税売上込六10%」を確認済み)。顧問先ごとに固定なので、
    入力JSONの `sales_business_type` で受け取る。
    """
    raw = data.get("sales_business_type")
    if raw is None:
        return ""
    return _BUSINESS_TYPE_KANJI.get(str(raw).strip(), "")


def _tax_options(business_type: str) -> list:
    """税区分の選択肢。借方・貸方で同じ一覧を使う。

    借方＝仕入、貸方＝売上とは限らない(売上返品や値引では借方に売上科目が来る)
    ため、側で選択肢を分けず、選んだ税区分自体でインボイス欄の有無を決める。
    """
    return [
        {"value": "課対仕入込10%", "label": "課税仕入 10%", "invoice": True},
        {"value": "課対仕入込軽減8%", "label": "課税仕入 軽減8%", "invoice": True},
        {"value": "課対仕入込8%", "label": "課税仕入 8%(旧税率)", "invoice": True},
        {"value": "非課仕入", "label": "非課税仕入", "invoice": False},
        {"value": f"課税売上込{business_type}10%", "label": "課税売上 10%", "invoice": False},
        {"value": f"課税売上込{business_type}軽減8%", "label": "課税売上 軽減8%", "invoice": False},
        {"value": f"課税売上込{business_type}8%", "label": "課税売上 8%(旧税率)", "invoice": False},
        {"value": "非課売上", "label": "非課税売上", "invoice": False},
        {"value": "対象外", "label": "対象外(不課税)", "invoice": False},
    ]


def build_html(data: dict, suggested_filename: str) -> str:
    legs = data.get("legs", [])
    project_folder = _guess_project_folder(legs)
    business_type = _sales_business_type(data)

    # 画像は同じファイルが複数の伝票から参照されることがあるため、重複排除して埋め込む
    image_uris: "dict[str, str]" = {}
    missing_images: list[str] = []
    for leg in legs:
        path = leg.get("source_image", "")
        if not path or path in image_uris:
            continue
        uri = _to_data_uri(path)
        if uri is None:
            missing_images.append(path)
            image_uris[path] = ""
        else:
            image_uris[path] = uri

    warning_banner = ""
    if missing_images:
        items = "".join(f"<li>{html.escape(p)}</li>" for p in sorted(set(missing_images)))
        warning_banner = f"""
        <div class="global-warning">
          以下の証憑画像ファイルが見つかりませんでした(パスをご確認ください):
          <ul>{items}</ul>
        </div>"""

    save_hint = ""
    if project_folder:
        save_hint = f"""
        <div id="saveHint">
          保存先を選ぶ画面が出た場合は、次のフォルダを選んでください:<br>
          <code>{html.escape(project_folder)}</code>
        </div>"""

    # 税区分の選択肢をどちらの課税方式で作ったかを明示する。簡易課税の顧問先で
    # 事業区分の指定を忘れると、売上の税区分が本則課税の名称になってしまうため、
    # 人が確認する画面で気づけるようにしておく。
    if business_type:
        tax_mode_label = f"簡易課税(第{business_type}種事業)"
    else:
        tax_mode_label = "本則課税(事業区分なし)"
    tax_mode_note = f"""
        <div id="taxModeNote">
          税区分の選択肢は<strong>{html.escape(tax_mode_label)}</strong>用で作成しています。
          この案件の課税方式と違う場合は、この資料を使わずにご連絡ください。
        </div>"""

    initial_data_json = json.dumps(data, ensure_ascii=False)
    images_json = json.dumps(image_uris, ensure_ascii=False)
    suggested_filename_json = json.dumps(suggested_filename, ensure_ascii=False)
    tax_options_json = json.dumps(_tax_options(business_type), ensure_ascii=False)
    invoice_options_json = json.dumps(_INVOICE_OPTIONS, ensure_ascii=False)

    # 画面上の訂正をブラウザに一時保存するためのキー。元データの内容から作るので、
    # 同じチェック資料を開き直せば前回の訂正が戻り、別の案件の資料とは混ざらない
    # (ファイル名だけだと、顧問先が違っても同名になりうるため内容から作る)。
    doc_key = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    doc_key_json = json.dumps(doc_key)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>仕訳チェック資料</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; font-family: "Yu Gothic", "Meiryo", sans-serif;
    display: flex; height: 100vh; overflow: hidden; background: #f5f5f7;
  }}
  #imagePane {{
    flex: 1 1 50%; background: #2b2b2b; display: flex;
    align-items: center; justify-content: center; position: relative; overflow: hidden;
  }}
  #imageStage {{
    width: 100%; height: 100%; padding: 16px;
    display: flex; align-items: center; justify-content: center;
    transform-origin: center center; will-change: transform;
  }}
  #imagePane img {{
    max-width: 100%; max-height: 100%; box-shadow: 0 4px 16px rgba(0,0,0,.4);
    background: #fff; user-select: none; -webkit-user-drag: none;
  }}
  #imagePane .placeholder {{ color: #aaa; font-size: 15px; }}
  /* 拡大中はドラッグで動かせることを、カーソルの形で示す */
  #imagePane.zoomed #imageStage {{ cursor: grab; }}
  #imagePane.panning #imageStage {{ cursor: grabbing; }}
  #zoomBar {{
    position: absolute; top: 12px; right: 12px; display: none; gap: 6px; align-items: center;
    background: rgba(255,255,255,.94); border-radius: 8px; padding: 6px;
    box-shadow: 0 2px 10px rgba(0,0,0,.35); z-index: 5;
  }}
  #zoomBar.visible {{ display: flex; }}
  #zoomBar button {{
    appearance: none; -webkit-appearance: none; border: 1px solid #ccc; background: #fff;
    color: #333; border-radius: 5px; width: 32px; height: 30px; cursor: pointer;
    font-size: 17px; line-height: 1; padding: 0;
  }}
  #zoomBar button.wide {{ width: auto; padding: 0 10px; font-size: 12px; }}
  #zoomBar button:hover {{ background: #f0f0f0; }}
  #zoomBar button:disabled {{ color: #bbb; cursor: default; background: #f7f7f7; }}
  #zoomLabel {{
    font-size: 12px; color: #444; min-width: 46px; text-align: center;
    font-variant-numeric: tabular-nums;
  }}
  #zoomHint {{
    position: absolute; bottom: 10px; left: 12px; display: none;
    color: #ddd; font-size: 11px; background: rgba(0,0,0,.4);
    padding: 4px 8px; border-radius: 5px; pointer-events: none;
  }}
  #zoomHint.visible {{ display: block; }}
  #listPane {{
    flex: 1 1 50%; overflow-y: auto; padding: 12px; border-left: 1px solid #ddd;
  }}
  #listPane h1 {{ font-size: 16px; margin: 4px 8px 12px; color: #333; }}
  #saveHint {{
    background: #eef4ff; border: 1px solid #cfe0fb; border-radius: 6px;
    padding: 8px 12px; margin: 0 8px 10px; font-size: 12px; color: #2b4a7a; line-height: 1.6;
  }}
  #saveHint code {{ font-size: 12px; word-break: break-all; }}
  #taxModeNote {{
    background: #fff8e6; border: 1px solid #f0dfae; border-radius: 6px;
    padding: 8px 12px; margin: 0 8px 10px; font-size: 12px; color: #6b5320; line-height: 1.6;
  }}
  #taxModeNote strong {{ color: #4a3a12; }}
  #toolbar {{ display: flex; gap: 8px; margin: 4px 8px 10px; }}
  #toolbar button {{
    appearance: none; -webkit-appearance: none;
    font-size: 13px; padding: 7px 12px; border-radius: 6px; border: 1px solid #ccc;
    background: #fff; color: #333; cursor: pointer;
  }}
  #toolbar #saveBtn {{ background: #2f6fdb; color: #fff; border-color: #2f6fdb; font-weight: bold; }}
  #saveBtn:hover {{ background: #2559b3; }}
  #resetBtn:hover {{ background: #f2f2f2; }}
  #restoredBanner {{
    display: none; background: #e8f4ea; border: 1px solid #b7ddc0; border-radius: 6px;
    padding: 9px 14px; margin: 0 8px 12px; font-size: 13px; color: #2c5c39;
    align-items: center; gap: 10px;
  }}
  #restoredBanner.visible {{ display: flex; }}
  #discardDraftBtn {{
    appearance: none; -webkit-appearance: none; margin-left: auto; white-space: nowrap;
    font-size: 12px; padding: 5px 10px; border-radius: 5px;
    border: 1px solid #a9c9b2; background: #fff; color: #2c5c39; cursor: pointer;
  }}
  #discardDraftBtn:hover {{ background: #f0f7f2; }}
  #dirtyBanner {{
    display: none; background: #fff3cd; border: 1px solid #ffe08a; border-radius: 6px;
    padding: 9px 14px; margin: 0 8px 12px; font-size: 13px; color: #7a5c00;
  }}
  #savedNote {{
    display: none; background: #e6f4ea; border: 1px solid #b7dfc2; border-radius: 6px;
    padding: 9px 14px; margin: 0 8px 12px; font-size: 13px; color: #1e6b34;
  }}
  .global-warning {{
    background: #fff3cd; border: 1px solid #ffe08a; border-radius: 6px;
    padding: 10px 14px; margin: 0 8px 12px; font-size: 13px; color: #7a5c00;
  }}
  .voucher-card {{
    background: #fff; border: 1px solid #e0e0e0; border-radius: 8px;
    padding: 10px 12px; margin: 0 8px 10px; cursor: pointer;
    transition: border-color .15s, box-shadow .15s;
  }}
  .voucher-card:hover {{ border-color: #90b8e8; }}
  .voucher-card.selected {{ border-color: #2f6fdb; box-shadow: 0 0 0 2px rgba(47,111,219,.25); }}
  .card-header {{ display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }}
  .card-header .date-input {{ font-size: 13px; padding: 3px 5px; }}
  .card-header .closing-select {{ font-size: 12px; padding: 3px 4px; }}
  .card-total {{ margin-left: auto; font-weight: bold; color: #1a1a1a; font-size: 14px; }}
  .card-total.mismatch {{ color: #c0392b; }}
  .leg-block {{ border-top: 1px dashed #e5e5e5; padding: 8px 0; }}
  .leg-block:first-child {{ border-top: none; padding-top: 0; }}
  .leg-fields-row {{ display: flex; flex-wrap: wrap; gap: 4px; align-items: center; margin-bottom: 4px; }}
  .side-tag {{
    display: inline-block; width: 34px; flex: 0 0 auto; font-size: 11px;
    text-align: center; border-radius: 4px; padding: 2px 0; color: #fff;
  }}
  .side-tag.debit {{ background: #2f6fdb; }}
  .side-tag.credit {{ background: #d98a2b; }}
  .leg-fields-row input {{
    font-size: 12px; padding: 4px 6px; border: 1px solid #d5d5d5; border-radius: 4px;
    font-family: inherit;
  }}
  .f-account {{ width: 108px; }}
  .f-sub {{ width: 66px; }}
  .f-dept {{ width: 60px; }}
  .f-tax {{ width: 150px; }}
  .f-invoice {{ width: 132px; }}
  .f-tax, .f-invoice {{
    font-size: 13px; padding: 5px 4px; border: 1px solid #ccc; border-radius: 4px;
    background: #fff; color: #333;
  }}
  .f-invoice:disabled {{ background: #f2f2f2; color: #aaa; }}
  .f-amount {{
    width: 140px; text-align: right; font-variant-numeric: tabular-nums;
    font-size: 15px; font-weight: bold; padding: 6px 8px;
  }}
  .f-taxamount {{ width: 84px; text-align: right; font-variant-numeric: tabular-nums; }}
  .f-desc-wide {{ flex: 1 1 100%; width: 100%; }}
  .f-memo {{ width: 90px; }}
  .del-leg-btn {{
    margin-left: auto; border: none; background: none; color: #b23c17; cursor: pointer;
    font-size: 13px; padding: 2px 6px;
  }}
  .del-leg-btn:hover {{ text-decoration: underline; }}
  .add-leg-btn {{
    margin-top: 6px; font-size: 12px; padding: 5px 10px; border: 1px dashed #aaa;
    border-radius: 5px; background: #fafafa; cursor: pointer; color: #555;
  }}
  .add-leg-btn:hover {{ background: #f0f0f0; }}
  /* 伝票ごとの削除。誤操作を防ぐため、すぐ消さず「削除予定」として残し、
     取り消せるようにする(保存するJSONからは除かれる) */
  .del-voucher-btn {{
    appearance: none; -webkit-appearance: none; margin-left: auto;
    font-size: 12px; padding: 4px 10px; border-radius: 5px;
    border: 1px solid #e0b4b4; background: #fff; color: #a33; cursor: pointer;
  }}
  .del-voucher-btn:hover {{ background: #fdf0f0; }}
  .voucher-card.deleted {{
    opacity: .6; background: #f4f4f4; border-style: dashed; border-color: #bbb;
  }}
  .voucher-card.deleted .card-total {{ text-decoration: line-through; }}
  .voucher-card.deleted .del-voucher-btn {{
    border-color: #b4c8e0; color: #2f6fdb; font-weight: bold;
  }}
  .deleted-badge {{
    display: none; font-size: 12px; font-weight: bold; color: #a33;
    background: #fdeaea; border: 1px solid #e8c4c4; border-radius: 4px; padding: 2px 8px;
  }}
  .voucher-card.deleted .deleted-badge {{ display: inline-block; }}
  .missing-note {{ margin-top: 6px; font-size: 12px; color: #b23c17; }}
</style>
</head>
<body>
  <div id="imagePane">
    <div id="imageStage"><div class="placeholder">左の一覧から仕訳を選んでください</div></div>
    <div id="zoomBar">
      <button id="zoomOutBtn" type="button" title="縮小">−</button>
      <span id="zoomLabel">100%</span>
      <button id="zoomInBtn" type="button" title="拡大">＋</button>
      <button id="zoomResetBtn" class="wide" type="button" title="全体を表示する">全体</button>
    </div>
    <div id="zoomHint">マウスホイールで拡大・縮小／拡大中はドラッグで移動／ダブルクリックで切替</div>
  </div>
  <div id="listPane">
    {tax_mode_note}
    {save_hint}
    <div id="toolbar">
      <button id="saveBtn" type="button">変更をJSONとして保存(ダウンロード)</button>
      <button id="resetBtn" type="button">元に戻す</button>
    </div>
    <div id="restoredBanner">
      <span id="restoredText"></span>
      <button id="discardDraftBtn" type="button">破棄して最初の状態に戻す</button>
    </div>
    <div id="dirtyBanner">まだ保存(ダウンロード)していない変更があります。訂正が終わったら「変更をJSONとして保存」を押してください。</div>
    <div id="savedNote"></div>
    {warning_banner}
    <h1 id="countLabel"></h1>
    <div id="cardsContainer"></div>
  </div>
<script>
  const INITIAL_DATA = {initial_data_json};
  const IMAGES = {images_json};
  const SUGGESTED_FILENAME = {suggested_filename_json};
  const TAX_OPTIONS = {tax_options_json};
  const INVOICE_OPTIONS = {invoice_options_json};
  const DOC_KEY = {doc_key_json};

  let VOUCHER_DATA = null;
  let legUidCounter = 0;
  let currentSelectedVoucherId = null;
  let dirty = false;
  // 「削除予定」にした伝票のvoucher_id。実際にデータから消すのは保存時で、
  // それまでは画面上で取り消せる(誤操作で仕訳を失わないため)
  let deletedVouchers = new Set();

  function esc(s) {{
    s = (s === undefined || s === null) ? "" : String(s);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }}

  function fmtAmount(n) {{
    n = Number(n) || 0;
    return n.toLocaleString("ja-JP");
  }}

  function parseAmount(str) {{
    return parseInt(String(str).replace(/,/g, ""), 10) || 0;
  }}

  function cloneInitial() {{
    const d = JSON.parse(JSON.stringify(INITIAL_DATA));
    d.legs = d.legs || [];
    d.legs.forEach(leg => {{ leg._uid = "leg-" + (legUidCounter++); }});
    return d;
  }}

  function findLegByUid(uid) {{
    return VOUCHER_DATA.legs.find(l => l._uid === uid);
  }}

  function groupLegs(legs) {{
    const groups = new Map();
    const order = [];
    for (const leg of legs) {{
      if (!groups.has(leg.voucher_id)) {{ groups.set(leg.voucher_id, []); order.push(leg.voucher_id); }}
      groups.get(leg.voucher_id).push(leg);
    }}
    for (const g of groups.values()) g.sort((a, b) => (a.leg_no || 0) - (b.leg_no || 0));
    return {{ groups, order }};
  }}

  // ===== 画面上の訂正をブラウザに一時保存する =====
  // このHTMLは生成時のデータを埋め込んだ固定ファイルで、「変更をJSONとして保存」は
  // 別ファイルをダウンロードするだけなので、同じHTMLを開き直すと訂正前の状態に
  // 戻ってしまう。作業を中断して閉じても続きからやり直せるよう、訂正内容を
  // ブラウザ内に保存しておく。
  const STORAGE_KEY = "voucher-to-yayoi-review:" + DOC_KEY;

  function saveDraft() {{
    try {{
      localStorage.setItem(STORAGE_KEY, JSON.stringify({{
        savedAt: new Date().toISOString(),
        data: VOUCHER_DATA,
        deleted: Array.from(deletedVouchers),
      }}));
    }} catch (e) {{
      // 保存できない環境でも、その回の作業自体は続けられるので止めない
    }}
  }}

  function loadDraft() {{
    try {{
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    }} catch (e) {{
      return null;
    }}
  }}

  function clearDraft() {{
    try {{ localStorage.removeItem(STORAGE_KEY); }} catch (e) {{}}
  }}

  function formatSavedAt(iso) {{
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const p = n => String(n).padStart(2, "0");
    return `${{d.getFullYear()}}年${{d.getMonth() + 1}}月${{d.getDate()}}日 ${{p(d.getHours())}}:${{p(d.getMinutes())}}`;
  }}

  function markDirty() {{
    dirty = true;
    document.getElementById("dirtyBanner").style.display = "block";
    saveDraft();
  }}

  // 税区分の文字列を「基本区分」と「インボイス区分」に分解する。
  // どの選択肢にも当てはまらない値(想定外の税区分)は失わないよう、そのまま
  // 「その他」の選択肢として保持する。
  function splitTaxCategory(value) {{
    const raw = value || "";
    for (const opt of TAX_OPTIONS) {{
      if (raw === opt.value) return {{ base: opt.value, invoice: "", other: "" }};
      if (opt.invoice) {{
        for (const inv of INVOICE_OPTIONS) {{
          if (raw === opt.value + inv.value) return {{ base: opt.value, invoice: inv.value, other: "" }};
        }}
      }}
    }}
    return {{ base: "", invoice: "", other: raw }};
  }}

  function taxOptionByValue(value) {{
    return TAX_OPTIONS.find(o => o.value === value) || null;
  }}

  function taxSelectHTML(leg, side) {{
    const parts = splitTaxCategory(leg[side].tax_category);
    const opts = TAX_OPTIONS.map(o =>
      `<option value="${{esc(o.value)}}"${{o.value === parts.base ? " selected" : ""}}>${{esc(o.label)}}</option>`
    ).join("");
    // 未設定・想定外の値はそのまま選択肢として残す(黙って書き換えないため)
    const otherOpt = parts.base
      ? ""
      : `<option value="" selected>${{parts.other ? esc(parts.other) + "(そのまま)" : "(未設定)"}}</option>`;
    const invoiceApplies = parts.base ? !!(taxOptionByValue(parts.base) || {{}}).invoice : false;
    const invOpts = INVOICE_OPTIONS.map(o =>
      `<option value="${{esc(o.value)}}"${{o.value === parts.invoice ? " selected" : ""}}>${{esc(o.label)}}</option>`
    ).join("");
    const invBlank = `<option value=""${{parts.invoice ? "" : " selected"}}>${{invoiceApplies ? "(未選択)" : "—"}}</option>`;
    return `
          <select class="f-tax" data-uid="${{leg._uid}}" data-side="${{side}}" title="税区分">${{otherOpt}}${{opts}}</select>
          <select class="f-invoice" data-uid="${{leg._uid}}" data-side="${{side}}" title="インボイス区分(課税仕入のみ)"${{invoiceApplies ? "" : " disabled"}}>${{invBlank}}${{invOpts}}</select>`;
  }}

  function legBlockHTML(leg) {{
    return `
      <div class="leg-block">
        <div class="leg-fields-row">
          <span class="side-tag debit">借方</span>
          <input class="f-account" data-uid="${{leg._uid}}" data-field="debit.account" value="${{esc(leg.debit.account)}}" placeholder="勘定科目">
          <input class="f-sub" data-uid="${{leg._uid}}" data-field="debit.sub_account" value="${{esc(leg.debit.sub_account)}}" placeholder="補助科目">
          <input class="f-dept" data-uid="${{leg._uid}}" data-field="debit.department" value="${{esc(leg.debit.department)}}" placeholder="部門">${{taxSelectHTML(leg, "debit")}}
        </div>
        <div class="leg-fields-row">
          <span class="side-tag credit">貸方</span>
          <input class="f-account" data-uid="${{leg._uid}}" data-field="credit.account" value="${{esc(leg.credit.account)}}" placeholder="勘定科目">
          <input class="f-sub" data-uid="${{leg._uid}}" data-field="credit.sub_account" value="${{esc(leg.credit.sub_account)}}" placeholder="補助科目">
          <input class="f-dept" data-uid="${{leg._uid}}" data-field="credit.department" value="${{esc(leg.credit.department)}}" placeholder="部門">${{taxSelectHTML(leg, "credit")}}
        </div>
        <div class="leg-fields-row">
          <input class="f-amount" type="text" inputmode="numeric" data-uid="${{leg._uid}}" data-field="__amount" value="${{fmtAmount(leg.debit.amount)}}" placeholder="金額">
        </div>
        <div class="leg-fields-row">
          <input class="f-desc-wide" data-uid="${{leg._uid}}" data-field="description" value="${{esc(leg.description)}}" placeholder="摘要">
        </div>
        <div class="leg-fields-row">
          <input class="f-taxamount" type="text" inputmode="numeric" data-uid="${{leg._uid}}" data-field="__tax_amount" value="${{fmtAmount(leg.debit.tax_amount)}}" placeholder="消費税額">
          <input class="f-memo" data-uid="${{leg._uid}}" data-field="memo" value="${{esc(leg.memo)}}" placeholder="メモ">
          <button type="button" class="del-leg-btn" data-uid="${{leg._uid}}" title="この明細行を削除">✕ 削除</button>
        </div>
      </div>`;
  }}

  function buildCardHTML(voucherId, group) {{
    const first = group[0];
    const legsHtml = group.map(legBlockHTML).join("");
    const closing = first.closing_flag || "";
    const isDeleted = deletedVouchers.has(voucherId);
    return `
      <div class="voucher-card${{isDeleted ? " deleted" : ""}}" data-voucher-id="${{esc(voucherId)}}">
        <div class="card-header">
          <input type="date" class="date-input" data-voucher-id="${{esc(voucherId)}}" data-field="__date" value="${{esc(first.transaction_date)}}">
          <select class="closing-select" data-voucher-id="${{esc(voucherId)}}" data-field="__closing_flag">
            <option value="" ${{closing === "" ? "selected" : ""}}>(通常)</option>
            <option value="本決" ${{closing === "本決" ? "selected" : ""}}>本決算</option>
          </select>
          <span class="card-total" data-total-for="${{esc(voucherId)}}"></span>
          <span class="deleted-badge">削除予定</span>
          <button type="button" class="del-voucher-btn" data-voucher-id="${{esc(voucherId)}}">${{
            isDeleted ? "元に戻す" : "🗑 伝票ごと削除"
          }}</button>
        </div>
        <div class="legs-container">${{legsHtml}}</div>
        ${{isDeleted ? "" : `<button type="button" class="add-leg-btn" data-voucher-id="${{esc(voucherId)}}">＋ 明細行を追加(複合仕訳にする)</button>`}}
      </div>`;
  }}

  // 伝票そのものを削除する(明細行1件の削除ではなく、伝票まるごと)。
  // 誤って消しても取り戻せるよう、その場では消さずに「削除予定」として印を付け、
  // 保存(ダウンロード)するJSONから除く方式にしている。
  function toggleVoucherDeleted(voucherId) {{
    if (deletedVouchers.has(voucherId)) {{
      deletedVouchers.delete(voucherId);
    }} else {{
      const group = VOUCHER_DATA.legs.filter(l => l.voucher_id === voucherId);
      const label = (group[0] && group[0].description) || voucherId;
      const ok = confirm(
        "この伝票を削除しますか?\\n\\n" + label + "\\n\\n" +
        "保存(ダウンロード)するJSONから、この伝票の全明細が除かれます。\\n" +
        "この画面の「元に戻す」でいつでも取り消せます。"
      );
      if (!ok) return;
      deletedVouchers.add(voucherId);
    }}
    markDirty();
    renderAll();
  }}

  function updateCardTotals(voucherId) {{
    const legs = VOUCHER_DATA.legs.filter(l => l.voucher_id === voucherId)
      .sort((a, b) => (a.leg_no || 0) - (b.leg_no || 0));
    // "manual"の複合仕訳は、各legが最終出力行そのもの(合計行＋明細行)を表すため、
    // 全legの金額を単純合計すると二重計上になる。合計行(先頭のleg)の金額を使う。
    const isManual = legs.some(l => l.split_side === "manual");
    let debitTotal, creditTotal;
    if (isManual && legs.length > 0) {{
      debitTotal = Number(legs[0].debit.amount) || 0;
      creditTotal = Number(legs[0].credit.amount) || 0;
    }} else {{
      debitTotal = legs.reduce((s, l) => s + (Number(l.debit.amount) || 0), 0);
      creditTotal = legs.reduce((s, l) => s + (Number(l.credit.amount) || 0), 0);
    }}
    const span = document.querySelector('.card-total[data-total-for="' + CSS.escape(voucherId) + '"]');
    if (!span) return;
    if (debitTotal === creditTotal) {{
      span.textContent = fmtAmount(debitTotal) + " 円";
      span.classList.remove("mismatch");
    }} else {{
      span.textContent = "貸借不一致(借方" + fmtAmount(debitTotal) + " / 貸方" + fmtAmount(creditTotal) + ")";
      span.classList.add("mismatch");
    }}
  }}

  function renderAll() {{
    const {{ groups, order }} = groupLegs(VOUCHER_DATA.legs);
    const deletedCount = order.filter(vid => deletedVouchers.has(vid)).length;
    const remaining = order.length - deletedCount;
    document.getElementById("countLabel").textContent =
      "仕訳チェック資料(件数: " + order.length + ")" +
      (deletedCount ? "  ※ うち" + deletedCount + "件を削除予定(残り" + remaining + "件)" : "");
    const container = document.getElementById("cardsContainer");
    container.innerHTML = order.map(vid => buildCardHTML(vid, groups.get(vid))).join("");
    order.forEach(updateCardTotals);

    // 削除予定の伝票は、内容を見られるように残したうえで編集できないようにする
    // (「元に戻す」ボタンだけは押せる必要がある)
    container.querySelectorAll(".voucher-card.deleted").forEach(card => {{
      card.querySelectorAll("input, select, textarea, button").forEach(el => {{
        if (!el.classList.contains("del-voucher-btn")) el.disabled = true;
      }});
    }});

    if (currentSelectedVoucherId && groups.has(currentSelectedVoucherId)) {{
      const card = container.querySelector('.voucher-card[data-voucher-id="' + CSS.escape(currentSelectedVoucherId) + '"]');
      if (card) card.classList.add("selected");
    }}
  }}

  // ===== 証憑画像の拡大・縮小 =====
  // 倍率1.0は「ペインに収まる大きさ(全体表示)」を意味する。画像の実寸ではなく
  // 表示サイズを基準にしているので、画像の解像度によらず同じ操作感になる。
  const ZOOM_MIN = 1, ZOOM_MAX = 8, ZOOM_STEP = 1.25;
  let zoomScale = 1, zoomX = 0, zoomY = 0;
  let panning = false, panStartX = 0, panStartY = 0;

  function stageImage() {{
    return document.querySelector("#imageStage img");
  }}

  function clampPan() {{
    const pane = document.getElementById("imagePane");
    const img = stageImage();
    if (!img) {{ zoomX = 0; zoomY = 0; return; }}
    // 画像が画面外へ飛んでいかないよう、はみ出した分だけ動かせるようにする
    const maxX = Math.max(0, (img.clientWidth * zoomScale - pane.clientWidth) / 2);
    const maxY = Math.max(0, (img.clientHeight * zoomScale - pane.clientHeight) / 2);
    zoomX = Math.min(maxX, Math.max(-maxX, zoomX));
    zoomY = Math.min(maxY, Math.max(-maxY, zoomY));
  }}

  function applyZoom() {{
    const pane = document.getElementById("imagePane");
    clampPan();
    document.getElementById("imageStage").style.transform =
      "translate(" + zoomX + "px," + zoomY + "px) scale(" + zoomScale + ")";
    document.getElementById("zoomLabel").textContent = Math.round(zoomScale * 100) + "%";
    pane.classList.toggle("zoomed", zoomScale > 1);
    document.getElementById("zoomInBtn").disabled = zoomScale >= ZOOM_MAX - 1e-9;
    document.getElementById("zoomOutBtn").disabled = zoomScale <= ZOOM_MIN + 1e-9;
  }}

  function setZoom(next, anchorClientX, anchorClientY) {{
    const clamped = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, next));
    if (Math.abs(clamped - zoomScale) < 1e-9) return;
    if (typeof anchorClientX === "number") {{
      // カーソルの下にある位置が動かないように平行移動量を調整する
      const rect = document.getElementById("imagePane").getBoundingClientRect();
      const cx = anchorClientX - rect.left - rect.width / 2;
      const cy = anchorClientY - rect.top - rect.height / 2;
      zoomX = cx - (cx - zoomX) * clamped / zoomScale;
      zoomY = cy - (cy - zoomY) * clamped / zoomScale;
    }}
    zoomScale = clamped;
    if (zoomScale === ZOOM_MIN) {{ zoomX = 0; zoomY = 0; }}
    applyZoom();
  }}

  function showWholeImage() {{
    zoomScale = ZOOM_MIN; zoomX = 0; zoomY = 0;
    applyZoom();
  }}

  function setZoomControlsVisible(visible) {{
    document.getElementById("zoomBar").classList.toggle("visible", visible);
    document.getElementById("zoomHint").classList.toggle("visible", visible);
  }}

  function initZoomControls() {{
    const pane = document.getElementById("imagePane");
    document.getElementById("zoomInBtn").addEventListener("click", () => setZoom(zoomScale * ZOOM_STEP));
    document.getElementById("zoomOutBtn").addEventListener("click", () => setZoom(zoomScale / ZOOM_STEP));
    document.getElementById("zoomResetBtn").addEventListener("click", showWholeImage);

    pane.addEventListener("wheel", e => {{
      if (!stageImage()) return;
      e.preventDefault();  // ページ全体のスクロールではなく拡大縮小にする
      setZoom(zoomScale * (e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP), e.clientX, e.clientY);
    }}, {{ passive: false }});

    pane.addEventListener("dblclick", e => {{
      if (!stageImage()) return;
      if (zoomScale > ZOOM_MIN) showWholeImage();
      else setZoom(2.5, e.clientX, e.clientY);
    }});

    pane.addEventListener("pointerdown", e => {{
      if (zoomScale <= ZOOM_MIN || !stageImage()) return;
      panning = true;
      panStartX = e.clientX - zoomX;
      panStartY = e.clientY - zoomY;
      pane.classList.add("panning");
      pane.setPointerCapture(e.pointerId);
    }});
    pane.addEventListener("pointermove", e => {{
      if (!panning) return;
      zoomX = e.clientX - panStartX;
      zoomY = e.clientY - panStartY;
      applyZoom();
    }});
    const endPan = () => {{
      if (!panning) return;
      panning = false;
      pane.classList.remove("panning");
    }};
    pane.addEventListener("pointerup", endPan);
    pane.addEventListener("pointercancel", endPan);
    // ウィンドウ幅が変わると収まる大きさも変わるため、はみ出し量を再計算する
    window.addEventListener("resize", applyZoom);
  }}

  function showPlaceholder(message) {{
    document.getElementById("imageStage").innerHTML =
      '<div class="placeholder">' + message + '</div>';
    setZoomControlsVisible(false);
    showWholeImage();
  }}

  function selectVoucher(voucherId) {{
    currentSelectedVoucherId = voucherId;
    document.querySelectorAll(".voucher-card.selected").forEach(c => c.classList.remove("selected"));
    const card = document.querySelector('.voucher-card[data-voucher-id="' + CSS.escape(voucherId) + '"]');
    if (card) card.classList.add("selected");
    const leg = VOUCHER_DATA.legs.find(l => l.voucher_id === voucherId);
    const uri = leg && leg.source_image ? IMAGES[leg.source_image] : null;
    if (uri) {{
      document.getElementById("imageStage").innerHTML = '<img src="' + uri + '" alt="証憑画像">';
      setZoomControlsVisible(true);
      // 別の証憑に切り替えたら、まず全体が見える状態から始める
      showWholeImage();
    }} else if (leg && leg.source_image) {{
      showPlaceholder("この証憑画像ファイルが見つかりません");
    }} else {{
      showPlaceholder("この仕訳には証憑画像が登録されていません");
    }}
  }}

  function addLeg(voucherId) {{
    const group = VOUCHER_DATA.legs.filter(l => l.voucher_id === voucherId);
    const first = group[0];
    const maxLegNo = Math.max(0, ...group.map(l => l.leg_no || 0));
    VOUCHER_DATA.legs.push({{
      _uid: "leg-" + (legUidCounter++),
      voucher_id: voucherId,
      leg_no: maxLegNo + 1,
      transaction_date: first.transaction_date,
      closing_flag: first.closing_flag,
      // 直前の明細の借方・貸方をコピーしておく。複合仕訳では通常どちらか一方
      // (現金・預金口座など)が全明細で共通なので、変更が必要な側だけ書き換え
      // れば済むようにするため(もう片方は自動的に「同じ科目」として扱われる)。
      debit: Object.assign({{}}, first.debit, {{ amount: 0, tax_amount: 0 }}),
      credit: Object.assign({{}}, first.credit, {{ amount: 0, tax_amount: 0 }}),
      description: "",
      memo: "",
      split_side: first.split_side ?? null,
      source_image: first.source_image || "",
    }});
    currentSelectedVoucherId = voucherId;
    markDirty();
    renderAll();
  }}

  function removeLeg(uid) {{
    const leg = findLegByUid(uid);
    if (!leg) return;
    const count = VOUCHER_DATA.legs.filter(l => l.voucher_id === leg.voucher_id).length;
    if (count <= 1) {{
      alert(
        "この伝票には明細行が1件しかないため、明細行だけを削除することはできません。\\n" +
        "この伝票自体が不要な場合は、右上の「🗑 伝票ごと削除」を使ってください。"
      );
      return;
    }}
    currentSelectedVoucherId = leg.voucher_id;
    VOUCHER_DATA.legs = VOUCHER_DATA.legs.filter(l => l._uid !== uid);
    markDirty();
    renderAll();
  }}

  // 税区分の2つのドロップダウン(基本区分・インボイス区分)から、弥生の税区分名を
  // 組み立て直す。基本区分が課税仕入でなくなったら、インボイス区分は外して欄も
  // 選択不可にする。
  function handleTaxSelectEvent(t) {{
    const leg = findLegByUid(t.dataset.uid);
    if (!leg) return;
    const side = t.dataset.side;
    const block = t.closest(".leg-block");
    const baseSel = block.querySelector('.f-tax[data-side="' + side + '"]');
    const invSel = block.querySelector('.f-invoice[data-side="' + side + '"]');
    const base = baseSel.value;
    const opt = taxOptionByValue(base);
    const invoiceApplies = !!(opt && opt.invoice);

    invSel.disabled = !invoiceApplies;
    if (!invoiceApplies) invSel.value = "";
    invSel.querySelector('option[value=""]').textContent = invoiceApplies ? "(未選択)" : "—";

    leg[side].tax_category = base ? base + (invoiceApplies ? invSel.value : "") : "";
    updateCardTotals(leg.voucher_id);
    markDirty();
  }}

  function handleFieldEvent(e) {{
    const t = e.target;
    if (t.classList && (t.classList.contains("f-tax") || t.classList.contains("f-invoice"))) {{
      handleTaxSelectEvent(t);
      return;
    }}
    const field = t.dataset.field;
    if (!field) return;
    if (field === "__date") {{
      VOUCHER_DATA.legs.filter(l => l.voucher_id === t.dataset.voucherId).forEach(l => {{ l.transaction_date = t.value; }});
      markDirty();
      return;
    }}
    if (field === "__closing_flag") {{
      VOUCHER_DATA.legs.filter(l => l.voucher_id === t.dataset.voucherId).forEach(l => {{ l.closing_flag = t.value; }});
      markDirty();
      return;
    }}
    const uid = t.dataset.uid;
    const leg = uid ? findLegByUid(uid) : null;
    if (!leg) return;
    if (field === "__amount") {{
      const v = parseAmount(t.value);
      leg.debit.amount = v;
      leg.credit.amount = v;
    }} else if (field === "__tax_amount") {{
      const v = parseAmount(t.value);
      leg.debit.tax_amount = v;
      leg.credit.tax_amount = v;
    }} else if (field === "description" || field === "memo") {{
      leg[field] = t.value;
    }} else if (field.indexOf(".") !== -1) {{
      const [side, prop] = field.split(".");
      leg[side][prop] = t.value;
    }}
    updateCardTotals(leg.voucher_id);
    markDirty();
  }}

  function saveJSON() {{
    // 「削除予定」にした伝票を、ここで初めて実際に除く
    const keptLegs = VOUCHER_DATA.legs.filter(l => !deletedVouchers.has(l.voucher_id));
    const removedCount = VOUCHER_DATA.legs.length - keptLegs.length;
    if (keptLegs.length === 0) {{
      alert(
        "すべての伝票が削除予定になっているため、保存できません。\\n" +
        "少なくとも1件は「元に戻す」で残してください。"
      );
      return;
    }}
    if (removedCount > 0) {{
      const ok = confirm(
        "削除予定の伝票を除いて保存します。\\n\\n" +
        "除かれる明細: " + removedCount + "件\\n" +
        "保存される明細: " + keptLegs.length + "件\\n\\n" +
        "よろしいですか?"
      );
      if (!ok) return;
    }}

    const out = {{
      start_denpyo_no: VOUCHER_DATA.start_denpyo_no,
      // 簡易課税の事業区分は顧問先ごとの設定なので、保存し直しても失わないようにする
      ...(VOUCHER_DATA.sales_business_type != null
        ? {{ sales_business_type: VOUCHER_DATA.sales_business_type }}
        : {{}}),
      legs: keptLegs.map(leg => {{
        const copy = Object.assign({{}}, leg);
        delete copy._uid;
        return copy;
      }}),
    }};
    const blob = new Blob([JSON.stringify(out, null, 2)], {{ type: "application/json" }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = SUGGESTED_FILENAME;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    dirty = false;
    document.getElementById("dirtyBanner").style.display = "none";
    const note = document.getElementById("savedNote");
    note.textContent = "保存しました。ダウンロードフォルダの「" + SUGGESTED_FILENAME + "」を確認してください。";
    note.style.display = "block";
  }}

  function resetAll() {{
    if (!confirm("この画面で行った変更をすべて破棄して、最初の内容に戻しますか?")) return;
    discardDraft();
  }}

  // 保存しておいた訂正内容を捨てて、生成時の状態に戻す
  function discardDraft() {{
    clearDraft();
    VOUCHER_DATA = cloneInitial();
    currentSelectedVoucherId = null;
    dirty = false;
    deletedVouchers = new Set();  // 削除予定も取り消す
    document.getElementById("dirtyBanner").style.display = "none";
    document.getElementById("savedNote").style.display = "none";
    document.getElementById("restoredBanner").classList.remove("visible");
    showPlaceholder("左の一覧から仕訳を選んでください");
    renderAll();
  }}

  // 開いたときに、前回の訂正内容が残っていれば復元する
  function restoreDraftOrInitial() {{
    const draft = loadDraft();
    if (!draft || !draft.data || !Array.isArray(draft.data.legs)) {{
      VOUCHER_DATA = cloneInitial();
      return;
    }}
    VOUCHER_DATA = draft.data;
    deletedVouchers = new Set(draft.deleted || []);
    // 明細を追加したときにIDが衝突しないよう、採番を続きから始める
    let maxUid = -1;
    VOUCHER_DATA.legs.forEach(leg => {{
      const n = parseInt(String(leg._uid || "").replace("leg-", ""), 10);
      if (!isNaN(n) && n > maxUid) maxUid = n;
      if (!leg._uid) leg._uid = "leg-" + (++maxUid);
    }});
    legUidCounter = maxUid + 1;

    const when = formatSavedAt(draft.savedAt);
    document.getElementById("restoredText").textContent =
      "前回この画面で行った訂正内容を復元しました" + (when ? "(" + when + "時点)" : "") +
      "。この内容で続きから作業できます。";
    document.getElementById("restoredBanner").classList.add("visible");
    // 復元した内容はまだJSONとして保存されていないので、その旨も出す
    dirty = true;
    document.getElementById("dirtyBanner").style.display = "block";
  }}

  document.getElementById("saveBtn").addEventListener("click", saveJSON);
  document.getElementById("resetBtn").addEventListener("click", resetAll);

  const container = document.getElementById("cardsContainer");
  container.addEventListener("input", handleFieldEvent);
  container.addEventListener("change", handleFieldEvent);
  container.addEventListener("focusout", e => {{
    const t = e.target;
    if (!(t.classList && (t.classList.contains("f-amount") || t.classList.contains("f-taxamount")))) return;
    const leg = findLegByUid(t.dataset.uid);
    if (!leg) return;
    const value = t.dataset.field === "__amount" ? leg.debit.amount : leg.debit.tax_amount;
    t.value = fmtAmount(value);
  }});
  container.addEventListener("click", e => {{
    if (e.target.classList.contains("del-voucher-btn")) {{ e.stopPropagation(); toggleVoucherDeleted(e.target.dataset.voucherId); return; }}
    if (e.target.classList.contains("del-leg-btn")) {{ e.stopPropagation(); removeLeg(e.target.dataset.uid); return; }}
    if (e.target.classList.contains("add-leg-btn")) {{ e.stopPropagation(); addLeg(e.target.dataset.voucherId); return; }}
    if (e.target.closest("input, select, button")) return;
    const card = e.target.closest(".voucher-card");
    if (card) selectVoucher(card.dataset.voucherId);
  }});

  document.getElementById("discardDraftBtn").addEventListener("click", () => {{
    if (!confirm("復元した訂正内容を破棄して、最初の状態に戻しますか?")) return;
    discardDraft();
  }});

  initZoomControls();
  restoreDraftOrInitial();
  renderAll();
</script>
</body>
</html>"""


def create_review_shortcut(html_path: Path) -> Path:
    """デスクトップに、チェック資料HTMLを開くショートカットを作成する。"""
    icon_path = Path(__file__).resolve().parent / "review_icon.ico"
    return create_shortcut(
        desktop_dir() / SHORTCUT_NAME,
        html_path.resolve(),
        working_directory=html_path.resolve().parent,
        icon_path=icon_path,
        description="仕訳チェック資料(直前に作成した仕訳の確認・訂正用)",
    )


def main():
    parser = argparse.ArgumentParser(
        description="仕訳データと証憑画像から、確認・訂正できるチェック資料(HTML)を作る"
    )
    parser.add_argument("input", help="入力JSON")
    parser.add_argument("output", help="出力先.html")
    parser.add_argument(
        "--no-desktop-shortcut",
        action="store_true",
        help="デスクトップに「仕訳チェック資料」のショートカットを作らない",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not data.get("legs"):
        print("入力JSONにlegsが1件もありません。")
        raise SystemExit(1)

    suggested_filename = f"{output_path.stem}_修正済み.json"
    html_content = build_html(data, suggested_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"チェック資料を出力しました: {output_path}")

    if not args.no_desktop_shortcut:
        try:
            shortcut_path = create_review_shortcut(output_path)
            print(f"デスクトップに「{shortcut_path.stem}」のアイコンを作成しました(ダブルクリックで開けます)。")
        except ShortcutError as e:
            # ショートカットはあくまで利便性のためのものなので、失敗しても
            # チェック資料自体は使える。処理を止めずに知らせるだけにする。
            print(f"※ デスクトップのアイコン作成はできませんでした({e})。")
            print(f"　 チェック資料は {output_path} から直接開けます。")

    print("ブラウザで開くと、その場で仕訳内容を訂正できます(勘定科目・金額・摘要など)。")
    print(f'訂正後は「変更をJSONとして保存」ボタンを押すと "{suggested_filename}" としてダウンロードされます。')


if __name__ == "__main__":
    main()
