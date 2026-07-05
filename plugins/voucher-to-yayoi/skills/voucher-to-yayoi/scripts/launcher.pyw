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
import urllib.parse
from pathlib import Path

APP_NAME = "voucher-to-yayoi-launcher"
CONFIG_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_PATH = CONFIG_DIR / "config.json"

# ルートフォルダ内で、案件フォルダとしては扱わない名前(表示から除外する)
IGNORED_NAMES = {"desktop.ini", "Thumbs.db"}

# 新規プロジェクト作成時に用意するサブフォルダ名
VOUCHER_SUBFOLDER = "証憑書類"
REFERENCE_SUBFOLDER = "参考資料ファイル"

# 新規プロジェクトに同梱するCLAUDE.md(社内の決まり事)のひな形。
# Claude Codeがこのフォルダで作業を始めるたびに自動的に読み込まれる。
CLAUDE_MD_TEMPLATE = """# このフォルダについて

このフォルダは、証憑書類(領収書・請求書)から弥生会計の仕訳データを作成するための
案件フォルダです。「証憑仕訳処理」ランチャー(デスクトップのショートカット)から
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

## このフォルダの開き方

次回以降も、このフォルダはエクスプローラーから直接開くのではなく、デスクトップの
「証憑仕訳処理」ショートカット(ランチャー)から選んで開くこと。ランチャーを使うと、
証憑書類・参考資料ファイルの各フォルダをワンクリックで開けるほか、常に最新版の
スキルが使われる状態が保たれる。

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
    name = name.strip()
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


def main() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, simpledialog

    root_window = tk.Tk()
    root_window.title("証憑仕訳処理")
    root_window.geometry("440x560")

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

    root_label = tk.Label(root_window, text=f"置き場所: {root_folder}", anchor="w", wraplength=420)
    root_label.pack(fill="x", padx=10, pady=(10, 0))

    tk.Label(root_window, text="案件一覧(クリックで選択)", anchor="w").pack(fill="x", padx=10, pady=(10, 0))

    list_frame = tk.Frame(root_window)
    list_frame.pack(fill="both", expand=True, padx=10, pady=5)
    scrollbar = tk.Scrollbar(list_frame)
    scrollbar.pack(side="right", fill="y")
    listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=("Yu Gothic UI", 11))
    listbox.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=listbox.yview)
    listbox.bind("<<ListboxSelect>>", on_listbox_select)

    detail_frame = tk.LabelFrame(root_window, text="選んだ案件で作業を始める")
    detail_frame.pack(fill="x", padx=10, pady=(0, 10))

    selected_label = tk.Label(detail_frame, text="案件を選択してください", anchor="w")
    selected_label.pack(fill="x", padx=8, pady=(6, 4))

    folder_buttons_frame = tk.Frame(detail_frame)
    folder_buttons_frame.pack(fill="x", padx=8)
    open_voucher_btn = tk.Button(
        folder_buttons_frame, text="📁 証憑書類を開く", command=on_open_voucher_folder, state="disabled",
    )
    open_voucher_btn.pack(side="left", expand=True, fill="x")
    open_reference_btn = tk.Button(
        folder_buttons_frame, text="📁 参考資料ファイルを開く", command=on_open_reference_folder, state="disabled",
    )
    open_reference_btn.pack(side="left", expand=True, fill="x", padx=(6, 0))

    start_btn = tk.Button(
        detail_frame, text="▶ 作業を開始する(Claudeを起動)", command=on_start_work, state="disabled",
        bg="#2f6fdb", fg="white",
    )
    start_btn.pack(fill="x", padx=8, pady=8)

    button_frame = tk.Frame(root_window)
    button_frame.pack(fill="x", padx=10, pady=(0, 10))
    tk.Button(button_frame, text="＋ 新規プロジェクト", command=on_new_project).pack(side="left")
    tk.Button(button_frame, text="置き場所を変更", command=on_change_root_folder).pack(side="right")

    refresh_project_list()
    root_window.mainloop()


if __name__ == "__main__":
    main()
