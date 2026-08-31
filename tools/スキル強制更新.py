"""voucher-to-yayoiスキルを、GitHub上の最新版に強制的に合わせる(単体で動く)。

スキル本体の版に依存しないため、**スキルが古くて自動更新が効かなくなったPCでも
そのまま実行できる**。しばらくアプリを使っていなかったPCで、最新の機能が反映
されない場合に使う。

なぜこれが必要か:
  スキルの自動更新は、スキル自身の中にある仕組みで動いている。そのため、
  スキルが古いと「古い(不具合のある)更新処理」が動くことになり、何度セッションを
  開き直しても最新にならない状態から抜け出せないことがある。この状態を外から
  断ち切るためのもの。

行うこと:
  1. Claude Desktopが持っているマーケットプレイスの複製を、GitHub上の内容に
     強制的に合わせる(枝分かれしていても確実に揃う)
  2. 実際に読み込まれるキャッシュフォルダへ反映する
  Python実行環境(venv)は保持するので作り直しは不要。Claude Desktopアプリ自身が
  管理する設定ファイル(installed_plugins.json 等)には一切触れない。

使い方:
    python スキル強制更新.py          調べるだけ(変更しない)
    python スキル強制更新.py --repair 最新版に強制的に合わせる

実行後は、**新しいセッションを開始**すると反映される。
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PLUGIN_NAME = "voucher-to-yayoi"

CLAUDE_DIR = Path.home() / ".claude"
# Claude Desktopがセッションごとにスキルを展開する場所。ここに置かれているPCには
# gitの複製が存在せず、この道具では直せない(実機で確認済み)。黙って
# 「修復はありません」で終わると次に何をすればよいか分からないため、検出して伝える。
APPDATA_CLAUDE = Path(os.environ.get("APPDATA", "")) / "Claude"


def find_marketplace_dir():
    """マーケットプレイスの複製フォルダを探す。

    フォルダ名を決め打ちしてはいけない。marketplace.jsonの名前
    (voucher-to-yayoi-marketplace)とGitHubのリポジトリ名
    (voucher-to-kaikei-marketplace)が異なるため、登録の仕方によってPC上の
    フォルダ名がどちらにもなりうる。実際に、リポジトリ名で登録されていたPCで
    「マーケットプレイス経由ではない」と誤判定した。
    """
    root = CLAUDE_DIR / "plugins" / "marketplaces"
    if not root.is_dir():
        return None
    for d in sorted(root.iterdir()):
        if (d / ".git").is_dir() and (d / "plugins" / PLUGIN_NAME).is_dir():
            return d
    return None


def find_cache_roots():
    root = CLAUDE_DIR / "plugins" / "cache"
    if not root.is_dir():
        return []
    return [d / PLUGIN_NAME for d in sorted(root.iterdir()) if (d / PLUGIN_NAME).is_dir()]


MARKETPLACE_DIR = find_marketplace_dir() or (CLAUDE_DIR / "plugins" / "(見つかりません)")
CACHE_ROOTS = find_cache_roots()
CACHE_ROOT = CACHE_ROOTS[0] if CACHE_ROOTS else (CLAUDE_DIR / "plugins" / "(見つかりません)")

VENV_RELPATH = Path("scripts") / ".venv"
VENV_STASH_NAME = ".venv-keep"


def run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


# GitHub上の最新のSKILL.mdを直接取りに行くための場所(公開リポジトリ)。
# gitの複製が無い配置では比較対象が手元に無く、「古いのか最新なのか判定できない」
# という役に立たない診断になってしまうため、大元から取得して突き合わせる。
RAW_SKILL_URL = (
    "https://raw.githubusercontent.com/teamtks/voucher-to-kaikei-marketplace/main/"
    f"plugins/{PLUGIN_NAME}/skills/{PLUGIN_NAME}/SKILL.md"
)


def digest_bytes(data: bytes) -> str:
    # 改行の違い(CRLF/LF)は中身の違いではない。取り出し方によって変わるため、
    # 揃えてから指紋を取らないと、同じ内容が別物として表示されてしまう。
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:12]


def digest(path: Path) -> str:
    try:
        return digest_bytes(path.read_bytes())
    except OSError:
        return "(読めません)"


def fetch_reference_digest() -> "str | None":
    """GitHub上の最新版の指紋を取得する。取れなければNone。"""
    try:
        with urllib.request.urlopen(RAW_SKILL_URL, timeout=20) as r:
            return digest_bytes(r.read())
    except Exception:
        return None


def find_skill_mds() -> "list[Path]":
    found = []
    for pattern in ("plugins/cache/**/SKILL.md", "plugins/marketplaces/**/SKILL.md", "skills/**/SKILL.md"):
        for p in CLAUDE_DIR.glob(pattern):
            if PLUGIN_NAME in str(p):
                found.append(p)
    # セッションごとに展開される配置は~/.claudeの外にあるため、別に拾う。ここを
    # 見落とすと「このPCにSKILL.mdは1件も無い」という誤った表示になる。
    for skill_dir in find_session_deployments():
        md = skill_dir / "SKILL.md"
        if md.is_file():
            found.append(md)
    return sorted(set(found))


def clone_skill_dir() -> Path:
    return MARKETPLACE_DIR / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME


def find_session_deployments() -> "list[Path]":
    """セッションごとに展開される配置を探す。"""
    root = APPDATA_CLAUDE / "local-agent-mode-sessions"
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob(f"**/skills/{PLUGIN_NAME}") if p.is_dir())


def explain_unsupported_layout() -> None:
    """この道具では直せない配置だったとき、次にすべきことを伝える。"""
    print("  この道具では直せない配置です。")
    print()
    found = find_session_deployments()
    if found:
        print("  スキルは、Claude Desktopがセッションごとに展開する場所にあります:")
        for p in found[:3]:
            print(f"    {p}")
        if len(found) > 3:
            print(f"    (ほか {len(found) - 3} 件)")
        print()
        print("  この配置にはgitの複製が無いため、GitHubと突き合わせて直すことが")
        print("  できません。")
    else:
        print(f"  {CLAUDE_DIR / 'plugins'} が見つかりませんでした。")
        print("  マーケットプレイス経由でのインストールが行われていないようです。")
    print()
    print("  → 手順書の【段階2 削除して入れ直す】を行ってください。")
    print("     1. 設定 ▸ カスタマイズ ▸ プラグイン ▸ Voucher to yayoi ▸「⋮」▸ 削除")
    print("     2.「参照」を押し、上部の「個人用」タブを開く")
    print("     3. 「証憑→弥生インポートデータ作成」を選んでインストール")
    print()
    print("     ※「+」からの登録は不要です。プラグインを削除しても、マーケット")
    print("       プレイスの登録は残るため「すでにあります」と表示されます。")


def diagnose() -> None:
    print("=" * 68)
    print("【1】インストール形態")
    print("=" * 68)
    if (MARKETPLACE_DIR / ".git").is_dir():
        print(f"  マーケットプレイス経由: {MARKETPLACE_DIR}")
        for label, cmd in (
            ("取得元URL", ["git", "remote", "get-url", "origin"]),
            ("ブランチ", ["git", "branch", "--show-current"]),
            ("現在の内容", ["git", "log", "--oneline", "-1"]),
            ("未コミット変更", ["git", "status", "--porcelain"]),
        ):
            r = run(cmd, cwd=MARKETPLACE_DIR)
            print(f"    {label}: {r.stdout.strip()[:150] or '(なし)'}")
        if run(["git", "fetch", "origin"], cwd=MARKETPLACE_DIR).returncode == 0:
            behind = run(["git", "rev-list", "--count", "HEAD..origin/main"], cwd=MARKETPLACE_DIR).stdout.strip()
            ahead = run(["git", "rev-list", "--count", "origin/main..HEAD"], cwd=MARKETPLACE_DIR).stdout.strip()
            print(f"    GitHubより遅れている: {behind} コミット")
            print(f"    GitHubに無い独自の変更: {ahead} コミット")
        else:
            print("    ！ GitHubに接続できません(ネットワークまたは認証を確認)")
    else:
        print("  マーケットプレイス経由ではありません(内部クローンが見つかりません)")
        print()
        explain_unsupported_layout()

    print()
    print("=" * 68)
    print("【2】このPC内のSKILL.md(Claudeが読む可能性がある場所すべて)")
    print("=" * 68)
    # 基準はGitHub上の最新版そのもの。手元の複製に頼らないため、gitの複製が無い
    # 配置(セッション展開型)のPCでも新旧を判定できる。
    ref = fetch_reference_digest()
    if ref:
        print(f"  基準(GitHub上の最新版): {ref}")
    else:
        reference = clone_skill_dir() / "SKILL.md"
        ref = digest(reference) if reference.is_file() else None
        if ref:
            print(f"  ！ GitHubに接続できないため、手元の複製を基準にします: {ref}")
        else:
            print("  ！ GitHubに接続できず、手元にも比較対象がありません。")
            print("     新旧の判定はできません(ネットワークを確認してください)。")

    found = find_skill_mds()
    if not found:
        print("  このPCにSKILL.mdが見つかりませんでした。")
    stale = []
    for p in found:
        d = digest(p)
        if ref is None:
            mark = "   "
        elif d == ref:
            mark = "OK "
        else:
            mark = "！古"
            stale.append(p)
        print(f"  {mark} {d}  {p}")
    print()
    if ref and stale:
        print("  「！古」が付いた場所は、GitHubの最新版と内容が違います。")
    elif ref and found:
        print("  すべて最新の内容です。")


def replace_skill_dir(src: Path, dest: Path) -> None:
    """venvを残したまま、スキルの中身を入れ替える。"""
    venv_dir = dest / VENV_RELPATH
    stash = dest.parent.parent / VENV_STASH_NAME
    stashed = False
    if venv_dir.is_dir():
        if stash.exists():
            shutil.rmtree(stash)
        venv_dir.rename(stash)
        stashed = True
    try:
        shutil.rmtree(dest)
        shutil.copytree(src, dest)
    finally:
        if stashed:
            restored = dest / VENV_RELPATH
            restored.parent.mkdir(parents=True, exist_ok=True)
            if restored.exists():
                shutil.rmtree(restored)
            stash.rename(restored)


def repair() -> None:
    print()
    print("=" * 68)
    print("最新版に強制的に合わせます")
    print("=" * 68)

    if not (MARKETPLACE_DIR / ".git").is_dir():
        explain_unsupported_layout()
        return

    if run(["git", "fetch", "origin"], cwd=MARKETPLACE_DIR).returncode != 0:
        print("  ！ GitHubから取得できませんでした。ネットワークと認証を確認してください。")
        return

    reset = run(["git", "reset", "--hard", "origin/main"], cwd=MARKETPLACE_DIR)
    if reset.returncode != 0:
        print(f"  ！ 内部クローンを揃えられませんでした: {reset.stderr.strip()[:200]}")
        return
    print(f"  取得した内容: {run(['git', 'log', '--oneline', '-1'], cwd=MARKETPLACE_DIR).stdout.strip()}")

    src = clone_skill_dir()
    if not src.is_dir():
        print(f"  ！ 取得した内容の中にスキルが見つかりません: {src}")
        return
    if not CACHE_ROOTS:
        print("  キャッシュフォルダがありません(プラグインが未インストールの可能性)。")
        return

    running = Path(sys.executable).resolve()
    for version_dir in [v for root in CACHE_ROOTS for v in sorted(root.iterdir())]:
        if not version_dir.is_dir():
            continue
        dest = version_dir / "skills" / PLUGIN_NAME
        try:
            inside = running.is_relative_to(dest.resolve()) if dest.is_dir() else False
        except (OSError, ValueError):
            inside = False
        if inside:
            print(f"  ！ 更新できません: {dest}")
            print("     このスクリプトを、入れ替え対象の中にあるPythonで実行しています。")
            print("     システムのPython(通常は `python`)で実行し直してください。")
            continue
        if dest.is_dir():
            replace_skill_dir(src, dest)
        else:
            shutil.copytree(src, dest)
        print(f"  反映しました: {dest}")

    print()
    print("完了しました。**新しいセッションを開始**すると反映されます")
    print("(いま開いているセッションの内容は入れ替わりません)。")


def main() -> None:
    parser = argparse.ArgumentParser(description="スキルを最新版に強制的に合わせる")
    parser.add_argument("--repair", action="store_true", help="最新版に強制的に合わせる")
    args = parser.parse_args()

    diagnose()
    if args.repair:
        repair()
    else:
        print()
        print("※ 調べただけで、何も変更していません。")
        print("  最新版に合わせるには、末尾に --repair を付けて実行してください:")
        print(f"      python \"{Path(__file__).name}\" --repair")


if __name__ == "__main__":
    main()
