"""証憑仕訳処理のプロジェクトを選ぶ・作るための小さなランチャー。

デスクトップのショートカットから起動する想定。ルートフォルダ(このPC上で
案件フォルダをまとめて置く場所)を初回に選ばせて記憶し、以降はその中の
案件一覧を表示する。

案件を一覧から選ぶと、いきなりClaudeを起動するのではなく、まず
「証憑書類」「参考資料ファイル」フォルダをエクスプローラーで開くボタンと、
「作業を開始する(Claudeを起動)」ボタンを表示する。証憑・参考資料の投入が
先に必要なため、この一手間を挟むことで作業前にファイルを入れ忘れる事故を防ぐ。
「作業を開始する」を押すと、Claude Desktopをそのフォルダの作業ディレクトリで
開く(claude://code/new?folder=... リンク)。

このスクリプト自体はUI/起動処理のみを担い、ロジック部分(設定の読み書き・
プロジェクト一覧・新規作成・リンク組み立て)は関数として分離しているため、
GUIを起動せずにテストできる。
"""
import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
import urllib.parse
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

APP_NAME = "voucher-to-yayoi-launcher"
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"

# ルートフォルダ内で、案件フォルダとしては扱わない名前(表示から除外する)
IGNORED_NAMES = {"desktop.ini", "Thumbs.db"}

# 新規プロジェクト作成時に用意するサブフォルダ名
VOUCHER_SUBFOLDER = "証憑書類"
REFERENCE_SUBFOLDER = "参考資料ファイル"

# 「㈲」「㈱」等のCJK互換文字は、Claude Desktopがフォルダを開くリンクを処理する際に
# 正規化されて別の文字列(例:「(有)」)に変わってしまい、実際のフォルダ名と
# 一致しなくなる不具合が実機で確認された。案件名に含まれていたら、素の文字列に
# 自動的に置き換える。
_UNSAFE_NAME_CHARS = {
    "㈲": "有限会社 ",
    "㈱": "株式会社 ",
    "㈳": "社団法人 ",
    "㈴": "合名会社 ",
    "㈵": "合資会社 ",
    "㈶": "財団法人 ",
}


def sanitize_project_name(name: str) -> str:
    for bad, good in _UNSAFE_NAME_CHARS.items():
        name = name.replace(bad, good)
    return name.strip()

# 新規プロジェクトに同梱するCLAUDE.md(社内の決まり事)のひな形。
# Claude Codeがこのフォルダで作業を始めるたびに自動的に読み込まれる。
#
# raw文字列(r""")にしているのは、Windowsのパスを例示するため。通常の文字列だと
# `\2026`が8進エスケープとして解釈されて別の文字に化けてしまう。
CLAUDE_MD_TEMPLATE = r"""# このフォルダについて

このフォルダは、証憑書類(領収書・請求書)から弥生会計の仕訳データを作成するための
案件フォルダです。「仕訳.TeamTKS」ランチャー(デスクトップのショートカット)から
作成・オープンされています。

## フォルダの中身と役割

- **証憑書類/** — 仕訳を起票する「対象」。処理したい領収書・請求書のPDF/JPG/PNG
  をここに入れる。
- **参考資料ファイル/** — 仕訳を切るための「判断材料」。勘定科目一覧・キーワード
  対応表・過去の元帳などを入れる。**この中のファイル自体を仕訳の対象にしてはならない。**
  あくまで科目やルールを判定するための参照データとして使う。

対象と参考資料を取り違えると、参考資料の中身から誤って仕訳を生成してしまう事故に
なるため、作業前にどちらのフォルダに何を入れたか必ず確認すること。

## 基本ルール

- **このフォルダの仕訳作業には、必ず`voucher-to-yayoi`スキルを使うこと。**
  「この証憑を仕訳にして」のように話しかければ自動的に使われる。
- **通帳・銀行取引明細・総勘定元帳からの仕訳も、すべて`voucher-to-yayoi`で行う。**
  他に似た用途のスキル(`bank-ledger-to-yayoi`など)が使える状態にあっても、
  **このフォルダでは使ってはならない。** それらは黒塗りも仕訳チェック資料の生成も
  行わないため、下の2つのルールを満たせない。実際に、通帳6件が黒塗りされないまま
  読み取られ、チェック資料も証憑画像の無い別物が作られた事故が起きている。
  参考資料に総勘定元帳や勘定科目一覧のPDFが入っていると、そちらのスキルが
  選ばれやすくなるため、特に注意すること。
- 証憑画像の宛名部分は、Claudeに読み取らせる前に必ずローカルで黒塗りする(スキルが
  自動で行う)。宛名には自社名など機微な情報が含まれるため、この手順は省略しない。
- 金額・勘定科目などの読み取り結果は、必ず人の目で確認してから確定させる。読み取り
  内容を鵜呑みにせず、証憑と見比べて確認する一手間が、間違いを防ぐ最後の砦になる。
- 弥生形式のファイルを作る前に、必ず「仕訳チェック資料」(HTML)を作成し、内容を
  確認・訂正してから最終ファイルを生成すること。
- 1つの伝票で「借方・貸方の両方が複数科目に分かれる」複雑な仕訳(給与仕訳など)を
  直接依頼された場合は、`split_side="manual"`による対応が可能。詳細はスキルの
  SKILL.mdを参照。

## この案件の会計ソフト

**未確認**(初回の作業時に利用者に確認し、「弥生会計」または「会計大将」に書き換える)

出力先の会計ソフトによって作れる仕訳の形が変わる(会計大将は1伝票1明細の単純仕訳のみ・
補助科目なし・科目コード表が別途必要)。そのため証憑を読み始める前に確認すること。

## 消費税の課税方式

**未確認**(初回の作業時に確認し、「本則課税」または「簡易課税(第○種事業)」に書き換える)

簡易課税の場合、売上の税区分名に事業区分が入る(例: 第六種事業なら`課税売上込六10%`)。
入力JSONに`"sales_business_type": "六"`を指定する必要があるため、第何種かまで記録すること。

## インポート用ファイルの生成先

**既定のまま(デスクトップ)**

`仕訳インポート_YYYYMMDD.txt`という名前でデスクトップに出力されます。
別の場所に出したい場合は、上の行をフルパスだけに書き換えてください
(例: `Z:\共有\会計データ\2026年度`)。

※ Claudeへの注意: この行が「既定のまま」の場合は、出力先を指定せずに実行すること
(デスクトップのパスを自分で組み立てて渡すと、OneDrive環境で利用者から見えない
場所に出力されてしまう)。フルパスが書かれている場合だけ、その場所を渡す。

## この案件で得た気づき

作業を通じてこの案件(取引先)に固有の気づき(よく使う勘定科目のパターン、
誤読されやすい表記など)があれば、Claudeが下に日付付きで追記していく。
まだ気づきは記録されていない。

## このフォルダの開き方

次回以降も、このフォルダはエクスプローラーから直接開くのではなく、デスクトップの
「仕訳.TeamTKS」ショートカット(ランチャー)から選んで開くこと。ランチャーを使うと、
証憑書類・参考資料ファイルの各フォルダをワンクリックで開けるほか、常に最新版の
スキルが使われる状態が保たれる。

## 運用ルール(Claudeへの指示)

- チャットの返事は簡潔な日本語で行うこと。
- 使用者の許可なく、このプロジェクトフォルダ内はもちろん、PC内のファイル・
  プログラム・設定等を削除しないこと。
- ファイルの削除が必要な場合(許可を得た上で)も、いきなりPCから消すのではなく、
  このプロジェクトフォルダ内に「削除済み」フォルダを作成し、その中に移動すること。
- 新たにプログラム等のインストールが必要な場合は、必ず使用者の許可を事前に得る
  こと。ただし、`voucher-to-yayoi`スキルの初回セットアップ(Python本体・必要な
  ライブラリの自動インストール)はこの限りではなく、これまで通り自動で行ってよい。

## 困ったときは

手順通りに進めてもうまくいかない場合や、表示される内容が分からない場合は、
無理に自己判断で進めず、以下にご連絡ください。

連絡先: ＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿＿
"""


def load_config() -> dict:
    if not CONFIG_PATH.is_file():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def get_root_folder() -> "Path | None":
    config = load_config()
    root = config.get("root_folder")
    if root and Path(root).is_dir():
        return Path(root)
    return None


def set_root_folder(path: "str | Path") -> None:
    config = load_config()
    config["root_folder"] = str(path)
    save_config(config)


def list_projects(root: Path) -> list[str]:
    """ルートフォルダ直下のサブフォルダ名一覧(案件名)を、名前順で返す。"""
    if not root.is_dir():
        return []
    names = [
        p.name for p in root.iterdir()
        if p.is_dir() and p.name not in IGNORED_NAMES and not p.name.startswith(".")
    ]
    return sorted(names, key=str.lower)


def create_project(root: Path, name: str) -> Path:
    """案件名フォルダを、証憑書類/参考資料ファイルの空フォルダとCLAUDE.md付きで作成する。"""
    name = sanitize_project_name(name)
    if not name:
        raise ValueError("案件名が空です")
    project_dir = root / name
    if project_dir.exists():
        raise FileExistsError(f"「{name}」は既に存在します")
    (project_dir / VOUCHER_SUBFOLDER).mkdir(parents=True)
    (project_dir / REFERENCE_SUBFOLDER).mkdir(parents=True)
    (project_dir / "CLAUDE.md").write_text(CLAUDE_MD_TEMPLATE, encoding="utf-8")
    return project_dir


def ensure_claude_md(project_dir: Path) -> bool:
    """案件フォルダにCLAUDE.mdが無ければ、ひな形を書き込む。

    「＋新規プロジェクト」で新規作成した案件には create_project() が必ずCLAUDE.mdを
    付けるが、既に手作業で作られていたフォルダを「置き場所を変更」で後から取り込んだ
    場合は create_project() を通らないため、CLAUDE.md が無いまま使われてしまう
    (実際にこの状態で会計ソフト・課税方式の確認欄が無く、確認が行われない不具合が
    起きたことを確認済み)。案件を開くたびに毎回チェックし、無ければ補う。

    既にCLAUDE.mdがある場合は何もしない(内容の上書きは絶対にしない)。
    戻り値は「今回新たに作成したかどうか」。
    """
    claude_md_path = project_dir / "CLAUDE.md"
    if claude_md_path.is_file():
        return False
    claude_md_path.write_text(CLAUDE_MD_TEMPLATE, encoding="utf-8")
    return True


def ensure_project_structure(project_dir: Path) -> "list[str]":
    """案件フォルダに、必要な下位フォルダとCLAUDE.mdを揃える。

    「＋新規プロジェクト」で作った案件には create_project() が一式を付けるが、
    既にあったフォルダを「置き場所を変更」で後から取り込んだ場合はそこを通らない。
    その結果「証憑書類」「参考資料ファイル」が無いまま作業が始まり、Claudeが
    「資料がありません」「フォルダを指定してください」と言い出す事象が実際に起きた
    (CLAUDE.mdについては同じ不具合を先に直したが、下位フォルダが漏れていた)。
    案件を開くたびに毎回補う。

    作るのは空のフォルダとひな形だけで、既にあるものの中身には一切触れない。
    戻り値は、今回新たに作ったものの名前。
    """
    created = []
    for sub in (VOUCHER_SUBFOLDER, REFERENCE_SUBFOLDER):
        subdir = project_dir / sub
        if not subdir.is_dir():
            subdir.mkdir(parents=True, exist_ok=True)
            created.append(sub)
    if ensure_claude_md(project_dir):
        created.append("CLAUDE.md")
    return created


def _system_python() -> "Path | None":
    """スキルフォルダの外にあるPythonを探す。

    このランチャー自体はスキルフォルダ内のvenvのPythonで動いている。そのPythonを
    外部の仕組み(黒塗りの安全装置のフック等)に使わせると、スキルを入れ替えた
    ときに使用中で消せなかったり、置き場所が変わって動かなくなったりするため、
    外側のPythonを明示的に探す。
    """
    skill_dir = Path(__file__).resolve().parent.parent
    for name in ("python", "python3", "py"):
        found = shutil.which(name)
        if not found:
            continue
        candidate = Path(found).resolve()
        try:
            if not candidate.is_relative_to(skill_dir):
                return candidate
        except ValueError:
            return candidate
    return None


# >>> Git版のみ: 自動最新化
# この目印で囲んだ範囲は、Git非依存の配布キットを作るときに丸ごと取り除かれる
# (キット再作成.py)。キットでも必要な処理を、この範囲の中に置かないこと。
def refresh_skill(timeout: int = 90) -> "tuple[bool, str]":
    """作業を始める前に、スキルの内容をGitHub上の最新版に合わせる。

    Claude自身にも最新化させているが、それはセッションが始まってからの実行に
    なるため、反映されるのは次のセッションからだった。ここで先に済ませておけば、
    これから開くセッションが最初から最新の内容で動く。

    ネットワークが無い・GitHubに繋がらない等で失敗しても、作業自体は続けられる
    ようにする(戻り値で知らせるだけで、起動は止めない)。
    """
    script = Path(__file__).resolve().parent / "refresh_marketplace_cache.py"
    if not script.is_file():
        return False, "最新化スクリプトが見つかりませんでした"

    python = _system_python()
    if python is None:
        return False, "システムのPythonが見つかりませんでした"

    try:
        result = subprocess.run(
            [str(python), str(script)],
            capture_output=True, text=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return False, "最新化に時間がかかりすぎたため中断しました"
    except OSError as e:
        return False, f"最新化を実行できませんでした({e})"

    output = (result.stdout or "").strip()
    if result.returncode != 0:
        return False, output or "最新化に失敗しました"
    return True, output
# <<< Git版のみ: 自動最新化


class _SettingsError(Exception):
    """利用者の設定ファイルを、安全に書き換えられなかったことを表す。"""


def _edit_user_settings(edit) -> bool:
    """利用者の設定ファイル(~/.claude/settings.json)を、壊さずに書き換える。

    そこには他のフックや権限設定も入っているため、次の手順を必ず守る:
      - 読めない・形式が違うときは、一切書き換えずに中止する
      - 初回の書き換え前に控えを取る
      - 別ファイルに書いてから差し替える(書き換え途中で落ちても壊れない)

    edit(settings) は設定を直接書き換え、変更したときだけTrueを返す。形式が想定と
    違う場合は _SettingsError を投げてよい。戻り値は実際に書き込んだかどうか。
    """
    try:
        settings = (
            json.loads(USER_SETTINGS.read_text(encoding="utf-8-sig")) if USER_SETTINGS.is_file() else {}
        )
    except (OSError, ValueError) as e:
        raise _SettingsError(f"設定ファイルを読めません: {e}") from e
    if not isinstance(settings, dict):
        raise _SettingsError("設定ファイルの形式が想定と異なります")

    if not edit(settings):
        return False

    try:
        if USER_SETTINGS.is_file():
            backup = USER_SETTINGS.with_name("settings.json.bak_voucher-to-yayoi")
            if not backup.exists():
                shutil.copyfile(USER_SETTINGS, backup)
        USER_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        tmp = USER_SETTINGS.with_name("settings.json.tmp_voucher-to-yayoi")
        tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, USER_SETTINGS)
    except OSError as e:
        raise _SettingsError(f"設定ファイルを書き換えられません: {e}") from e
    return True


def skill_access_root() -> Path:
    """Claude Codeに「作業フォルダ」として登録する、スキルの置き場所。

    プラグインとして配布された場合、スキルは
        ~/.claude/plugins/cache/<配布元>/voucher-to-yayoi/<版>/skills/voucher-to-yayoi
    に置かれ、<版>のフォルダ名は更新のたびに変わる。版のフォルダを登録すると更新の
    たびに古くなるため、版の1つ上(このプラグインのフォルダ)を登録する。
    ~/.claude/skills に直接置かれている場合は、そのフォルダ自体を登録する。
    """
    skill_dir = Path(__file__).resolve().parent.parent
    plugin_dir = skill_dir.parents[2]
    looks_like_plugin = (
        skill_dir.parent.name == "skills"
        and plugin_dir.name == skill_dir.name
        and "cache" in (p.name for p in plugin_dir.parents)
    )
    return plugin_dir if looks_like_plugin else skill_dir


def register_skill_dir() -> "str | None":
    """スキルの置き場所を、Claude Codeの作業フォルダとして登録する。

    スキルの本体は案件フォルダの外にある。Claude Codeは作業フォルダの外を初めて
    読むときに確認を出し、自動モードの安全機能は外部での実行を止める。3回続けて
    止めると自動モードは手動に戻る。これが「仕訳を切って」と言った直後に「その他の
    フォルダ」の確認が出て、自動モードが手動に戻る症状の正体だった(ローカル版の
    利用先で実際に発生)。

    permissions.additionalDirectories に登録したフォルダは、元の作業フォルダと
    同じ扱いになり確認なしで読める(公式ドキュメントに明記)。登録するのは読み取りの
    許可だけで、そのフォルダの設定は読み込まれない。

    既に登録済みなら何もしない。失敗したときだけ、利用者に伝える文言を返す。
    """
    try:
        _register_additional_dir(skill_access_root())
    except _SettingsError as e:
        return f"スキルの置き場所を登録できませんでした({e})"
    return None


def register_case_root() -> "str | None":
    """案件フォルダをまとめて置いている場所を、Claude Codeの作業フォルダとして登録する。

    利用先のPCによっては、ランチャーから開いたセッションの案件フォルダが、最初の
    送信のときに外れて「フォルダなし」になる(アプリ側の挙動で、こちらでは再現も
    防止もできない)。そのままでは案件フォルダが作業フォルダの外になり、読むたびに
    確認が出て、自動モードも手動に戻ってしまう。案件フォルダの親を登録しておけば、
    フォルダが外れても、確認なしで本来の案件フォルダを読み書きして作業を続けられる
    (どの案件かは、ランチャーが入力欄に入れる【案件: 名前】で判断する)。

    置き場所がまだ決まっていなければ何もしない。失敗したときだけ文言を返す。
    """
    root = get_root_folder()
    if root is None:
        return None
    try:
        _register_additional_dir(root)
    except _SettingsError as e:
        return f"案件フォルダの置き場所を登録できませんでした({e})"
    return None


def _register_additional_dir(folder: Path) -> bool:
    """permissions.additionalDirectories に1つ加える。加えたらTrue、登録済みならFalse。"""
    wanted = os.path.normcase(os.path.normpath(str(folder)))

    def add(settings: dict) -> bool:
        permissions = settings.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            raise _SettingsError("設定ファイルの形式が想定と異なります")
        dirs = permissions.setdefault("additionalDirectories", [])
        if not isinstance(dirs, list):
            raise _SettingsError("設定ファイルの形式が想定と異なります")
        # Windowsのパスは大文字小文字を区別しない。表記揺れで二重登録しないよう揃えて比べる
        if any(isinstance(d, str) and os.path.normcase(os.path.normpath(d)) == wanted for d in dirs):
            return False
        dirs.append(str(folder))
        return True

    return _edit_user_settings(add)


HOOK_SOURCE = Path(__file__).resolve().parent / "hooks" / "block_unmasked_vouchers.py"
HOOK_INSTALLED = Path.home() / ".claude" / "hooks" / "block_unmasked_vouchers.py"
USER_SETTINGS = Path.home() / ".claude" / "settings.json"
HOOK_MARK = "block_unmasked_vouchers"


def install_masking_guard() -> "str | None":
    """黒塗りしていない証憑の読み取りを拒否する安全装置を、このPCに有効化する。

    黒塗りの決まりはSKILL.mdとCLAUDE.mdの両方に書いてあったが、実際に破られた。
    別のスキルが選ばれた時点で指示文は効かないため、読み取り自体を拒否する
    仕組み(PreToolUseフック)に置き換える。

    スキル本体は更新のたびに置き場所が変わりうるので、フックの本体は
    `~/.claude/hooks/`へ複製し、設定はそこを指す。毎回の起動で複製を上書きする
    ため、スキルを更新すればフックも一緒に新しくなる。

    既に登録済みの場合は何もしない。利用者の他のフック設定には触れない。
    戻り値は、利用者に知らせるべきことがあればその文言。
    """
    if not HOOK_SOURCE.is_file():
        return None
    try:
        HOOK_INSTALLED.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HOOK_SOURCE, HOOK_INSTALLED)
    except OSError as e:
        return f"黒塗りの安全装置を配置できませんでした({e})"

    python = _system_python()
    if python is None:
        return "黒塗りの安全装置を登録できませんでした(Pythonが見つかりません)"

    def add(settings: dict) -> bool:
        hooks = settings.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise _SettingsError("設定ファイルの形式が想定と異なります")
        pre = hooks.setdefault("PreToolUse", [])
        if not isinstance(pre, list):
            raise _SettingsError("設定ファイルの形式が想定と異なります")
        if HOOK_MARK in json.dumps(pre, ensure_ascii=False):
            return False  # 既に登録済み
        pre.append({
            "matcher": "Read",
            "hooks": [{
                "type": "command",
                "command": f'"{python}" "{HOOK_INSTALLED}"',
                "timeout": 15,
                "statusMessage": "証憑が黒塗り済みか確認中...",
            }],
        })
        return True

    try:
        added = _edit_user_settings(add)
    except _SettingsError as e:
        return f"黒塗りの安全装置を登録できませんでした({e})"
    if not added:
        return None
    return (
        "黒塗りしていない証憑の読み取りを止める安全装置を、このPCに追加しました。\n\n"
        "以後、黒塗り前の証憑を読み取ろうとすると自動的に止まります。"
    )


LAST_OPEN_RECORD = Path.home() / ".claude" / "voucher-to-yayoi-last-open.json"


def record_last_open(folder: Path) -> None:
    """これから開こうとしている案件フォルダを控えておく。

    `claude://code/new?folder=...`は、まれにフォルダ指定が失われ、案件フォルダでは
    なく一時作業領域(scratch-workspaces)でセッションが開かれることがある
    (実機で、9月に始まったセッション19件中12件で発生。アプリは起動済みで、
    こちらからは防げない)。
    そうなるとCLAUDE.mdも証憑書類フォルダも読めず、Claudeは「対象ファイルが無い」
    としか言えなくなる。

    ここに控えておけば、スキル側が「どの案件を開こうとしたのか」を名指しして
    開き直しを案内できる。失敗しても起動は妨げない。
    """
    try:
        LAST_OPEN_RECORD.parent.mkdir(parents=True, exist_ok=True)
        LAST_OPEN_RECORD.write_text(
            json.dumps(
                {"project": str(folder), "opened_at": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


CASE_MARKER_PREFIX = "【案件: "
CASE_MARKER_SUFFIX = "】"

# 入力欄の先頭に案件名の目印を入れるかどうか。職員のPC(この版)では入れない。
# 目印が要るのは、最初の送信で案件フォルダが外れる現象が起きる配布先だけで、
# 職員には不要との判断(利用者の指示)。配布キットを作るときに、キット再作成.py が
# この行を True に書き換える。
CASE_MARKER_IN_PROMPT = False


def case_marker(folder: Path) -> str:
    """入力欄の先頭に入れておく、案件名の目印。

    利用先のPCによっては、最初の送信のときに案件フォルダが外れ、セッションが
    「フォルダなし」になる。控えのファイル(最後に開いた案件)だけでは、案件を
    続けて開いたときに後のもので上書きされ、先に開いたセッションで別の顧問先の
    仕訳を作ってしまいかねない。送信する文章そのものに案件名を残せば、フォルダが
    外れても、セッションごとに正しい案件が必ず分かる。利用者はこの後ろに、
    これまでどおり依頼を書けばよい。
    """
    return f"{CASE_MARKER_PREFIX}{folder.name}{CASE_MARKER_SUFFIX}\n"


def build_claude_open_uri(folder: Path) -> str:
    """指定フォルダを作業ディレクトリにしてClaude Codeセッションを開くURI。

    folder を先頭に置く。入力欄への事前入力(q)は、フォルダの受け渡しとは独立に
    届くことを実機で確認済み。目印は配布キットでだけ入れる(CASE_MARKER_IN_PROMPT)。
    """
    encoded = urllib.parse.quote(str(folder), safe="")
    uri = f"claude://code/new?folder={encoded}"
    if CASE_MARKER_IN_PROMPT:
        uri += "&q=" + urllib.parse.quote(case_marker(folder), safe="")
    return uri


def open_project_in_claude(folder: Path) -> None:
    ensure_project_structure(folder)
    record_last_open(folder)
    uri = build_claude_open_uri(folder)
    os.startfile(uri)


def open_folder(folder: Path) -> None:
    """フォルダをエクスプローラーで開く(無ければ作ってから開く)。"""
    folder.mkdir(parents=True, exist_ok=True)
    os.startfile(str(folder))


# 配色(生成済みアイコンの色味に合わせたポップな暖色系パレット)
_COLOR_BG = "#FFF8F3"
_COLOR_HEADER = "#FF7A59"
_COLOR_HEADER_TEXT = "#FFFFFF"
_COLOR_ACCENT = "#4ECDC4"
_COLOR_ACCENT_DARK = "#37B6AC"
_COLOR_SECONDARY = "#FFB86B"
_COLOR_SECONDARY_DARK = "#F5A94E"
_COLOR_TEXT = "#4E342E"
_COLOR_MUTED = "#8D6E63"
_COLOR_CARD_BG = "#FFFFFF"
_COLOR_SELECT_BG = "#FFE0D6"
_COLOR_BORDER = "#F0E4DC"
_COLOR_BORDEAUX = "#722F37"


def _flat_button(parent, text, command, bg, fg="white", font=("Yu Gothic UI", 10, "bold")):
    return tk.Button(
        parent, text=text, command=command, bg=bg, fg=fg,
        activebackground=bg, activeforeground=fg, font=font,
        relief="flat", bd=0, padx=12, pady=8, cursor="hand2",
        disabledforeground="#C9C2BB",
    )


def _enable_windows_dpi_awareness() -> None:
    """WindowsのディスプレイのDPI拡大設定(125%/150%等)がかかっている場合、
    素のtkinterはこれを考慮せず描画するため、文字がぼやけて薄く・読みにくく
    見えることがある。これをOSに伝えて、文字をくっきり描画させる。"""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _fit_window_to_content(window, shrinkable, min_shrinkable_height: int = 120) -> None:
    """並べ終えた部品が全部収まる大きさにウィンドウを合わせる。

    ディスプレイの拡大設定(125%/150%等)がかかっていると文字が大きく描画されるため、
    ウィンドウの大きさをピクセル数で決め打ちすると、下側のボタンがはみ出して
    見えなくなる(実機の125%環境で、必要な高さ721pxに対し固定値600pxで発生)。
    実際に必要な大きさを測ってから決めることで、どの拡大率でも収まるようにする。
    画面より大きくならないよう上限も掛ける。

    `shrinkable`は伸縮する部品(案件一覧)。ウィンドウを小さくする際に縮んでよいのは
    ここだけなので、それ以外の部分の高さを下限として設定する。
    """
    window.update_idletasks()
    need_w = window.winfo_reqwidth()
    need_h = window.winfo_reqheight()

    width = min(need_w, int(window.winfo_screenwidth() * 0.9))
    height = min(need_h, int(window.winfo_screenheight() * 0.9))
    window.geometry(f"{width}x{height}")

    fixed_h = need_h - shrinkable.winfo_reqheight()
    window.minsize(width, min(height, fixed_h + min_shrinkable_height))


def main() -> None:
    _enable_windows_dpi_awareness()

    root_window = tk.Tk()
    root_window.title("仕訳.TeamTKS")
    root_window.configure(bg=_COLOR_BG)
    # ウィンドウの大きさはここでは決めない。ディスプレイの拡大設定(125%等)によって
    # 文字の描画サイズが変わり、固定サイズだと下側のボタンがはみ出して見えなくなる
    # ため、部品を全部並べ終えたあとに必要な高さを測って決める(main()の末尾を参照)。

    state = {"root_folder": get_root_folder(), "selected_project": None}

    def prompt_for_root_folder(initial: "str | None" = None) -> "Path | None":
        documents = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        selected = filedialog.askdirectory(
            title="案件フォルダをまとめて置く場所を選んでください",
            initialdir=initial or (str(documents) if documents.is_dir() else str(Path.home())),
        )
        if not selected:
            return None
        return Path(selected)

    def ensure_root_folder() -> "Path | None":
        if state["root_folder"] is not None:
            return state["root_folder"]
        messagebox.showinfo(
            "初回セットアップ",
            "案件フォルダをまとめて置く場所を選んでください。\n"
            "次回からは自動的にこの場所が使われます。",
        )
        chosen = prompt_for_root_folder()
        if chosen is None:
            return None
        chosen.mkdir(parents=True, exist_ok=True)
        set_root_folder(chosen)
        state["root_folder"] = chosen
        return chosen

    def clear_selection() -> None:
        state["selected_project"] = None
        selected_label.config(text="案件を選択してください")
        open_voucher_btn.config(state="disabled")
        open_reference_btn.config(state="disabled")
        start_btn.config(state="disabled")

    def refresh_project_list() -> None:
        listbox.delete(0, tk.END)
        root_folder = state["root_folder"]
        if root_folder is None:
            return
        for name in list_projects(root_folder):
            listbox.insert(tk.END, name)
        clear_selection()

    def select_project_by_name(name: str) -> None:
        items = listbox.get(0, tk.END)
        if name not in items:
            return
        index = items.index(name)
        listbox.selection_clear(0, tk.END)
        listbox.selection_set(index)
        listbox.see(index)
        on_listbox_select()

    def on_listbox_select(_event=None) -> None:
        selection = listbox.curselection()
        if not selection:
            clear_selection()
            return
        name = listbox.get(selection[0])
        project_dir = state["root_folder"] / name
        state["selected_project"] = project_dir
        selected_label.config(text=f"選択中の案件: {name}")
        open_voucher_btn.config(state="normal")
        open_reference_btn.config(state="normal")
        start_btn.config(state="normal")

    def on_open_voucher_folder() -> None:
        project_dir = state["selected_project"]
        if project_dir is not None:
            open_folder(project_dir / VOUCHER_SUBFOLDER)

    def on_open_reference_folder() -> None:
        project_dir = state["selected_project"]
        if project_dir is not None:
            open_folder(project_dir / REFERENCE_SUBFOLDER)

    def on_start_work() -> None:
        project_dir = state["selected_project"]
        if project_dir is None:
            return

        # >>> Git版のみ: 自動最新化
        # セッションを開く前にスキルを最新化する。ここで済ませておかないと、
        # 反映されるのが次のセッションからになってしまう。
        original_label = start_btn["text"]
        start_btn.config(state="disabled", text="スキルを最新化しています…")
        root_window.update()
        try:
            ok, message = refresh_skill()
        finally:
            start_btn.config(state="normal", text=original_label)

        if not ok:
            messagebox.showwarning(
                "スキルを最新化できませんでした",
                f"{message}\n\n"
                "そのまま作業は始められますが、最新の機能が反映されていない可能性が"
                "あります。繰り返し出る場合は担当者にこの内容を伝えてください。",
            )
        # <<< Git版のみ: 自動最新化

        # 以下はGit版・配布キットの両方で必要。セッションを開く前に済ませること
        # (設定はセッション開始時に読み込まれるため、開いた後では効かない)。

        # 黒塗りしていない証憑を読めないようにする。スキルの最新化の後に行うことで、
        # 更新された安全装置がそのまま反映される。
        guard_notice = install_masking_guard()
        if guard_notice:
            messagebox.showinfo("安全装置について", guard_notice)

        # スキルの置き場所と、案件フォルダの置き場所を作業フォルダとして登録する。
        # 無いと、作業を始めた直後に「その他のフォルダ」の確認が出て、自動モードが
        # 手動に戻ってしまう(案件フォルダが外れて「フォルダなし」になったPCでも、
        # 後者があれば本来の案件フォルダで作業を続けられる)。
        for dir_notice in (register_skill_dir(), register_case_root()):
            if dir_notice:
                messagebox.showwarning("設定について", dir_notice)

        open_project_in_claude(project_dir)

    def on_new_project() -> None:
        root_folder = state["root_folder"]
        if root_folder is None:
            return
        name = simpledialog.askstring("新規プロジェクト", "新しい案件名(取引先名など)を入力してください:")
        if not name:
            return
        try:
            project_dir = create_project(root_folder, name)
        except (ValueError, FileExistsError) as e:
            messagebox.showerror("作成できません", str(e))
            return
        refresh_project_list()
        select_project_by_name(project_dir.name)
        # 作成直後は証憑・参考資料の投入が必要になるはずなので、両方すぐ開く
        open_folder(project_dir / VOUCHER_SUBFOLDER)
        open_folder(project_dir / REFERENCE_SUBFOLDER)

    def on_change_root_folder() -> None:
        chosen = prompt_for_root_folder(initial=str(state["root_folder"]) if state["root_folder"] else None)
        if chosen is None:
            return
        chosen.mkdir(parents=True, exist_ok=True)
        set_root_folder(chosen)
        state["root_folder"] = chosen
        root_label.config(text=f"置き場所: {chosen}")
        refresh_project_list()

    root_folder = ensure_root_folder()
    if root_folder is None:
        root_window.destroy()
        return

    header = tk.Frame(root_window, bg=_COLOR_HEADER)
    header.pack(fill="x")
    tk.Label(
        header, text="🧾 仕訳.TeamTKS", bg=_COLOR_HEADER, fg=_COLOR_HEADER_TEXT,
        font=("Yu Gothic UI", 16, "bold"), anchor="w",
    ).pack(fill="x", padx=14, pady=12)

    root_label = tk.Label(
        root_window, text=f"📂 置き場所: {root_folder}", anchor="w", wraplength=430,
        bg=_COLOR_BG, fg=_COLOR_MUTED, font=("Yu Gothic UI", 9),
    )
    root_label.pack(fill="x", padx=14, pady=(10, 0))

    tk.Label(
        root_window, text="案件一覧(クリックで選択)", anchor="w",
        bg=_COLOR_BG, fg=_COLOR_TEXT, font=("Yu Gothic UI", 10, "bold"),
    ).pack(fill="x", padx=14, pady=(12, 4))

    # 各フレームのpackはmain()の末尾でまとめて行う。下側のボタンを先に(side="bottom"で)
    # 配置し、伸縮する案件一覧を最後に配置することで、ウィンドウが小さいときに
    # ボタンではなく一覧の方が縮むようにするため。
    list_frame = tk.Frame(root_window, bg=_COLOR_BORDER, bd=0)
    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side="right", fill="y")
    listbox = tk.Listbox(
        list_frame, yscrollcommand=scrollbar.set, font=("Yu Gothic UI", 12, "bold"),
        bg=_COLOR_CARD_BG, fg=_COLOR_TEXT, relief="flat", bd=0,
        highlightthickness=1, highlightbackground=_COLOR_BORDER, highlightcolor=_COLOR_ACCENT,
        selectbackground=_COLOR_SELECT_BG, selectforeground=_COLOR_TEXT,
        activestyle="none",
    )
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)
    listbox.bind("<<ListboxSelect>>", on_listbox_select)

    detail_frame = tk.Frame(root_window, bg=_COLOR_CARD_BG, highlightthickness=1, highlightbackground=_COLOR_BORDER)

    tk.Frame(detail_frame, bg=_COLOR_ACCENT, height=4).pack(fill="x")

    selected_label = tk.Label(
        detail_frame, text="案件を選択してください", anchor="w",
        bg=_COLOR_CARD_BG, fg=_COLOR_TEXT, font=("Yu Gothic UI", 10, "bold"),
    )
    selected_label.pack(fill="x", padx=10, pady=(10, 6))

    folder_buttons_frame = tk.Frame(detail_frame, bg=_COLOR_CARD_BG)
    folder_buttons_frame.pack(fill="x", padx=10)
    open_voucher_btn = _flat_button(
        folder_buttons_frame, "📁 証憑書類を開く", on_open_voucher_folder, bg=_COLOR_SECONDARY, fg=_COLOR_BORDEAUX,
    )
    open_voucher_btn.config(state="disabled", activebackground=_COLOR_SECONDARY_DARK)
    open_voucher_btn.pack(side="left", expand=True, fill="x")
    open_reference_btn = _flat_button(
        folder_buttons_frame, "📁 参考資料ファイルを開く", on_open_reference_folder, bg=_COLOR_SECONDARY, fg=_COLOR_BORDEAUX,
    )
    open_reference_btn.config(state="disabled", activebackground=_COLOR_SECONDARY_DARK)
    open_reference_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

    start_btn = _flat_button(
        detail_frame, "▶  作業を開始する(Claudeを起動)", on_start_work, bg=_COLOR_ACCENT, fg=_COLOR_BORDEAUX,
        font=("Yu Gothic UI", 11, "bold"),
    )
    start_btn.config(state="disabled", activebackground=_COLOR_ACCENT_DARK)
    start_btn.pack(fill="x", padx=10, pady=10)

    button_frame = tk.Frame(root_window, bg=_COLOR_BG)
    _flat_button(button_frame, "＋ 新規プロジェクト", on_new_project, bg=_COLOR_HEADER).pack(side="left")
    _flat_button(
        button_frame, "置き場所を変更", on_change_root_folder, bg=_COLOR_BORDER, fg=_COLOR_TEXT,
        font=("Yu Gothic UI", 9),
    ).pack(side="right")

    # 下から順に配置する(先にpackした方が下に来る)。最後に案件一覧を残りの領域へ
    # 広げることで、ウィンドウを小さくしてもボタンが隠れず、一覧の方が縮む。
    button_frame.pack(side="bottom", fill="x", padx=14, pady=(0, 14))
    detail_frame.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
    list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    _fit_window_to_content(root_window, shrinkable=list_frame, min_shrinkable_height=120)

    refresh_project_list()
    root_window.mainloop()


if __name__ == "__main__":
    main()
