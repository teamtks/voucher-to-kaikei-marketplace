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
import subprocess
import sys
import tkinter as tk
import urllib.parse
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
CLAUDE_MD_TEMPLATE = """# このフォルダについて

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

- 証憑の処理には`voucher-to-yayoi`スキルを使うこと。「この証憑を仕訳にして」のように
  話しかければ自動的に使われる。
- 証憑画像の宛名部分は、Claudeに読み取らせる前に必ずローカルで黒塗りする(スキルが
  自動で行う)。宛名には自社名など機微な情報が含まれるため、この手順は省略しない。
- 金額・勘定科目などの読み取り結果は、必ず人の目で確認してから確定させる。読み取り
  内容を鵜呑みにせず、証憑と見比べて確認する一手間が、間違いを防ぐ最後の砦になる。
- 弥生形式のファイルを作る前に、必ず「仕訳チェック資料」(HTML)を作成し、内容を
  確認・訂正してから最終ファイルを生成すること。
- 1つの伝票で「借方・貸方の両方が複数科目に分かれる」複雑な仕訳(給与仕訳など)を
  直接依頼された場合は、`split_side="manual"`による対応が可能。詳細はスキルの
  SKILL.mdを参照。

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


def build_claude_open_uri(folder: Path) -> str:
    """指定フォルダを作業ディレクトリにしてClaude Codeセッションを開くURI。"""
    encoded = urllib.parse.quote(str(folder), safe="")
    return f"claude://code/new?folder={encoded}"


def open_project_in_claude(folder: Path) -> None:
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


def main() -> None:
    _enable_windows_dpi_awareness()

    root_window = tk.Tk()
    root_window.title("仕訳.TeamTKS")
    root_window.geometry("460x600")
    root_window.configure(bg=_COLOR_BG)

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
        if project_dir is not None:
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

    list_frame = tk.Frame(root_window, bg=_COLOR_BORDER, bd=0)
    list_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))
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
    detail_frame.pack(fill="x", padx=14, pady=(0, 12))

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
    button_frame.pack(fill="x", padx=14, pady=(0, 14))
    _flat_button(button_frame, "＋ 新規プロジェクト", on_new_project, bg=_COLOR_HEADER).pack(side="left")
    _flat_button(
        button_frame, "置き場所を変更", on_change_root_folder, bg=_COLOR_BORDER, fg=_COLOR_TEXT,
        font=("Yu Gothic UI", 9),
    ).pack(side="right")

    refresh_project_list()
    root_window.mainloop()


if __name__ == "__main__":
    main()
