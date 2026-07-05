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

使い方:
    python generate_review_html.py <入力JSON> <出力先.html>
"""
import base64
import html
import json
import mimetypes
import sys
from pathlib import Path


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "image/png"


def _to_data_uri(path: str) -> str | None:
    p = Path(path)
    if not p.is_file():
        return None
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{_guess_mime(path)};base64,{data}"


def build_html(data: dict, suggested_filename: str) -> str:
    legs = data.get("legs", [])

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

    initial_data_json = json.dumps(data, ensure_ascii=False)
    images_json = json.dumps(image_uris, ensure_ascii=False)
    suggested_filename_json = json.dumps(suggested_filename, ensure_ascii=False)

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
    align-items: center; justify-content: center; padding: 16px; overflow: auto;
  }}
  #imagePane img {{ max-width: 100%; max-height: 100%; box-shadow: 0 4px 16px rgba(0,0,0,.4); background: #fff; }}
  #imagePane .placeholder {{ color: #aaa; font-size: 15px; }}
  #listPane {{
    flex: 1 1 50%; overflow-y: auto; padding: 12px; border-left: 1px solid #ddd;
  }}
  #listPane h1 {{ font-size: 16px; margin: 4px 8px 12px; color: #333; }}
  #toolbar {{ display: flex; gap: 8px; margin: 4px 8px 10px; }}
  #toolbar button {{
    font-size: 13px; padding: 7px 12px; border-radius: 6px; border: 1px solid #ccc;
    background: #fff; cursor: pointer;
  }}
  #saveBtn {{ background: #2f6fdb; color: #fff; border-color: #2f6fdb; font-weight: bold; }}
  #saveBtn:hover {{ background: #2559b3; }}
  #resetBtn:hover {{ background: #f2f2f2; }}
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
  .f-tax {{ width: 108px; }}
  .f-amount, .f-taxamount {{ width: 84px; text-align: right; font-variant-numeric: tabular-nums; }}
  .f-desc {{ width: 150px; }}
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
  .missing-note {{ margin-top: 6px; font-size: 12px; color: #b23c17; }}
</style>
</head>
<body>
  <div id="imagePane"><div class="placeholder">左の一覧から仕訳を選んでください</div></div>
  <div id="listPane">
    <div id="toolbar">
      <button id="saveBtn" type="button">変更をJSONとして保存(ダウンロード)</button>
      <button id="resetBtn" type="button">元に戻す</button>
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

  let VOUCHER_DATA = null;
  let legUidCounter = 0;
  let currentSelectedVoucherId = null;
  let dirty = false;

  function esc(s) {{
    s = (s === undefined || s === null) ? "" : String(s);
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }}

  function fmtAmount(n) {{
    n = Number(n) || 0;
    return n.toLocaleString("ja-JP");
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

  function markDirty() {{
    dirty = true;
    document.getElementById("dirtyBanner").style.display = "block";
  }}

  function legBlockHTML(leg) {{
    return `
      <div class="leg-block">
        <div class="leg-fields-row">
          <span class="side-tag debit">借方</span>
          <input class="f-account" data-uid="${{leg._uid}}" data-field="debit.account" value="${{esc(leg.debit.account)}}" placeholder="勘定科目">
          <input class="f-sub" data-uid="${{leg._uid}}" data-field="debit.sub_account" value="${{esc(leg.debit.sub_account)}}" placeholder="補助科目">
          <input class="f-dept" data-uid="${{leg._uid}}" data-field="debit.department" value="${{esc(leg.debit.department)}}" placeholder="部門">
          <input class="f-tax" data-uid="${{leg._uid}}" data-field="debit.tax_category" value="${{esc(leg.debit.tax_category)}}" placeholder="税区分">
        </div>
        <div class="leg-fields-row">
          <span class="side-tag credit">貸方</span>
          <input class="f-account" data-uid="${{leg._uid}}" data-field="credit.account" value="${{esc(leg.credit.account)}}" placeholder="勘定科目">
          <input class="f-sub" data-uid="${{leg._uid}}" data-field="credit.sub_account" value="${{esc(leg.credit.sub_account)}}" placeholder="補助科目">
          <input class="f-dept" data-uid="${{leg._uid}}" data-field="credit.department" value="${{esc(leg.credit.department)}}" placeholder="部門">
          <input class="f-tax" data-uid="${{leg._uid}}" data-field="credit.tax_category" value="${{esc(leg.credit.tax_category)}}" placeholder="税区分">
        </div>
        <div class="leg-fields-row">
          <input class="f-amount" type="number" data-uid="${{leg._uid}}" data-field="__amount" value="${{Number(leg.debit.amount) || 0}}" placeholder="金額">
          <input class="f-taxamount" type="number" data-uid="${{leg._uid}}" data-field="__tax_amount" value="${{Number(leg.debit.tax_amount) || 0}}" placeholder="消費税額">
          <input class="f-desc" data-uid="${{leg._uid}}" data-field="description" value="${{esc(leg.description)}}" placeholder="摘要">
          <input class="f-memo" data-uid="${{leg._uid}}" data-field="memo" value="${{esc(leg.memo)}}" placeholder="メモ">
          <button type="button" class="del-leg-btn" data-uid="${{leg._uid}}" title="この明細行を削除">✕ 削除</button>
        </div>
      </div>`;
  }}

  function buildCardHTML(voucherId, group) {{
    const first = group[0];
    const legsHtml = group.map(legBlockHTML).join("");
    const closing = first.closing_flag || "";
    return `
      <div class="voucher-card" data-voucher-id="${{esc(voucherId)}}">
        <div class="card-header">
          <input type="date" class="date-input" data-voucher-id="${{esc(voucherId)}}" data-field="__date" value="${{esc(first.transaction_date)}}">
          <select class="closing-select" data-voucher-id="${{esc(voucherId)}}" data-field="__closing_flag">
            <option value="" ${{closing === "" ? "selected" : ""}}>(通常)</option>
            <option value="本決" ${{closing === "本決" ? "selected" : ""}}>本決算</option>
          </select>
          <span class="card-total" data-total-for="${{esc(voucherId)}}"></span>
        </div>
        <div class="legs-container">${{legsHtml}}</div>
        <button type="button" class="add-leg-btn" data-voucher-id="${{esc(voucherId)}}">＋ 明細行を追加(複合仕訳にする)</button>
      </div>`;
  }}

  function updateCardTotals(voucherId) {{
    const legs = VOUCHER_DATA.legs.filter(l => l.voucher_id === voucherId);
    const debitTotal = legs.reduce((s, l) => s + (Number(l.debit.amount) || 0), 0);
    const creditTotal = legs.reduce((s, l) => s + (Number(l.credit.amount) || 0), 0);
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
    document.getElementById("countLabel").textContent = "仕訳チェック資料(件数: " + order.length + ")";
    const container = document.getElementById("cardsContainer");
    container.innerHTML = order.map(vid => buildCardHTML(vid, groups.get(vid))).join("");
    order.forEach(updateCardTotals);
    if (currentSelectedVoucherId && groups.has(currentSelectedVoucherId)) {{
      const card = container.querySelector('.voucher-card[data-voucher-id="' + CSS.escape(currentSelectedVoucherId) + '"]');
      if (card) card.classList.add("selected");
    }}
  }}

  function selectVoucher(voucherId) {{
    currentSelectedVoucherId = voucherId;
    document.querySelectorAll(".voucher-card.selected").forEach(c => c.classList.remove("selected"));
    const card = document.querySelector('.voucher-card[data-voucher-id="' + CSS.escape(voucherId) + '"]');
    if (card) card.classList.add("selected");
    const leg = VOUCHER_DATA.legs.find(l => l.voucher_id === voucherId);
    const pane = document.getElementById("imagePane");
    const uri = leg && leg.source_image ? IMAGES[leg.source_image] : null;
    if (uri) {{
      pane.innerHTML = '<img src="' + uri + '" alt="証憑画像">';
    }} else if (leg && leg.source_image) {{
      pane.innerHTML = '<div class="placeholder">この証憑画像ファイルが見つかりません</div>';
    }} else {{
      pane.innerHTML = '<div class="placeholder">この仕訳には証憑画像が登録されていません</div>';
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
      debit: {{ account: "", sub_account: "", department: "", tax_category: "", amount: 0, tax_amount: 0 }},
      credit: {{ account: "", sub_account: "", department: "", tax_category: "", amount: 0, tax_amount: 0 }},
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
      alert("この伝票には明細行が1件しかないため、この画面からは削除できません。伝票ごと不要な場合は元のJSONファイルを編集してください。");
      return;
    }}
    currentSelectedVoucherId = leg.voucher_id;
    VOUCHER_DATA.legs = VOUCHER_DATA.legs.filter(l => l._uid !== uid);
    markDirty();
    renderAll();
  }}

  function handleFieldEvent(e) {{
    const t = e.target;
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
      const v = parseInt(t.value, 10) || 0;
      leg.debit.amount = v;
      leg.credit.amount = v;
    }} else if (field === "__tax_amount") {{
      const v = parseInt(t.value, 10) || 0;
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
    const out = {{
      start_denpyo_no: VOUCHER_DATA.start_denpyo_no,
      legs: VOUCHER_DATA.legs.map(leg => {{
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
    VOUCHER_DATA = cloneInitial();
    currentSelectedVoucherId = null;
    dirty = false;
    document.getElementById("dirtyBanner").style.display = "none";
    document.getElementById("savedNote").style.display = "none";
    document.getElementById("imagePane").innerHTML = '<div class="placeholder">左の一覧から仕訳を選んでください</div>';
    renderAll();
  }}

  document.getElementById("saveBtn").addEventListener("click", saveJSON);
  document.getElementById("resetBtn").addEventListener("click", resetAll);

  const container = document.getElementById("cardsContainer");
  container.addEventListener("input", handleFieldEvent);
  container.addEventListener("change", handleFieldEvent);
  container.addEventListener("click", e => {{
    if (e.target.classList.contains("del-leg-btn")) {{ e.stopPropagation(); removeLeg(e.target.dataset.uid); return; }}
    if (e.target.classList.contains("add-leg-btn")) {{ e.stopPropagation(); addLeg(e.target.dataset.voucherId); return; }}
    if (e.target.closest("input, select, button")) return;
    const card = e.target.closest(".voucher-card");
    if (card) selectVoucher(card.dataset.voucherId);
  }});

  VOUCHER_DATA = cloneInitial();
  renderAll();
</script>
</body>
</html>"""


def main():
    if len(sys.argv) != 3:
        print("使い方: python generate_review_html.py <入力JSON> <出力先.html>")
        raise SystemExit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not data.get("legs"):
        print("入力JSONにlegsが1件もありません。")
        raise SystemExit(1)

    suggested_filename = f"{output_path.stem}_修正済み.json"
    html_content = build_html(data, suggested_filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"チェック資料を出力しました: {output_path}")
    print("ブラウザで開くと、その場で仕訳内容を訂正できます(勘定科目・金額・摘要など)。")
    print(f'訂正後は「変更をJSONとして保存」ボタンを押すと "{suggested_filename}" としてダウンロードされます。')


if __name__ == "__main__":
    main()
