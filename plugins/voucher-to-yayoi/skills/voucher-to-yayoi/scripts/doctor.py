"""このスキルが「本当に最新の内容で動く状態か」を調べ、必要なら確実に直す。

`refresh_marketplace_cache.py`は通常の更新用だが、内部クローンが途中で壊れている
(早送りマージできない状態になっている)場合など、安全側に倒して何もせず終わる
ケースがある。その結果、何度セッションを開き直しても古い内容のまま、という状況が
実際に複数のPCで起きた。原因の切り分けに毎回時間がかかるため、状態をすべて表示し、
必要なら強制的に揃えられるようにする。

使い方:
    python doctor.py            調べるだけ(ファイルは一切変更しない)
    python doctor.py --repair   最新の内容に強制的に揃える

--repair は内部クローンをGitHub上の内容に強制的に合わせる(git reset --hard)。
この内部クローンはClaude Desktopが管理する取得用の複製であり、利用者が編集する
場所ではないため、消えて困る内容は無い。Claude Desktopアプリ自身が管理する
状態ファイル(installed_plugins.json 等)には一切触れない。
"""
import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

MARKETPLACE_NAME = "voucher-to-yayoi-marketplace"
PLUGIN_NAME = "voucher-to-yayoi"

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"
MARKETPLACE_DIR = CLAUDE_DIR / "plugins" / "marketplaces" / MARKETPLACE_NAME
CACHE_ROOT = CLAUDE_DIR / "plugins" / "cache" / MARKETPLACE_NAME / PLUGIN_NAME

_RELAUNCH_GUARD = "VOUCHER_TO_YAYOI_DOCTOR_RELAUNCHED"


def _run(args: list[str], cwd: Path):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _digest(path: Path) -> "str | None":
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


def _relaunch_outside_cache_if_needed() -> bool:
    """入れ替え対象の中のPythonで動いている場合、外側のPythonで起動し直す。

    マーケットプレイス経由だとvenvが入れ替え対象の中にあり、そのままでは使用中の
    ファイルを消せずに修復できないため。
    """
    if os.environ.get(_RELAUNCH_GUARD):
        return False
    try:
        if not Path(sys.executable).resolve().is_relative_to(CACHE_ROOT.resolve()):
            return False
    except (OSError, ValueError):
        return False

    cache_root = CACHE_ROOT.resolve()
    external = None
    for name in ("python", "python3", "py"):
        import shutil as _shutil
        found = _shutil.which(name)
        if found and not Path(found).resolve().is_relative_to(cache_root):
            external = Path(found).resolve()
            break
    if external is None:
        print("！ 入れ替え対象の中のPythonで実行されており、代わりに使えるPythonが見つかりません。")
        print("  システムのPythonで実行し直してください。")
        return True

    env = dict(os.environ, **{_RELAUNCH_GUARD: "1"})
    result = subprocess.run(
        [str(external), str(Path(__file__).resolve()), *sys.argv[1:]],
        env=env, capture_output=True, text=True,
    )
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    return True


def _find_all_skill_md() -> list[Path]:
    """このPC内にある、このスキルのSKILL.mdをすべて探す。"""
    found = []
    for pattern in ("plugins/cache/**/SKILL.md", "plugins/marketplaces/**/SKILL.md", "skills/**/SKILL.md"):
        for p in CLAUDE_DIR.glob(pattern):
            if PLUGIN_NAME in str(p):
                found.append(p)
    return sorted(set(found))


def _clone_skill_md() -> Path:
    return MARKETPLACE_DIR / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME / "SKILL.md"


def diagnose() -> dict:
    print("=" * 70)
    print("スキルの状態を調べています")
    print("=" * 70)

    info = {"has_clone": (MARKETPLACE_DIR / ".git").is_dir()}

    print("\n【1】インストール形態")
    if info["has_clone"]:
        print(f"  マーケットプレイス経由です: {MARKETPLACE_DIR}")
        remote = _run(["git", "remote", "get-url", "origin"], MARKETPLACE_DIR).stdout.strip()
        head = _run(["git", "log", "--oneline", "-1"], MARKETPLACE_DIR).stdout.strip()
        dirty = _run(["git", "status", "--porcelain"], MARKETPLACE_DIR).stdout.strip()
        print(f"    取得元      : {remote}")
        print(f"    現在の内容  : {head}")
        if dirty:
            print(f"    ！ 内部クローンに変更が残っています(これが更新を妨げます):")
            for line in dirty.splitlines()[:5]:
                print(f"        {line}")
        info["remote"], info["head"], info["dirty"] = remote, head, bool(dirty)
    else:
        print("  マーケットプレイス経由ではありません(スキルフォルダを直接使用)")

    print("\n【2】GitHub上の最新との比較")
    if info["has_clone"]:
        fetch = _run(["git", "fetch", "origin"], MARKETPLACE_DIR)
        if fetch.returncode != 0:
            print("  ！ 取得に失敗しました(ネットワーク未接続または認証の問題)")
            print(f"    {fetch.stderr.strip()[:200]}")
            info["fetch_ok"] = False
        else:
            info["fetch_ok"] = True
            behind = _run(["git", "rev-list", "--count", "HEAD..origin/main"], MARKETPLACE_DIR).stdout.strip()
            ahead = _run(["git", "rev-list", "--count", "origin/main..HEAD"], MARKETPLACE_DIR).stdout.strip()
            print(f"    GitHubより遅れているコミット数: {behind}")
            print(f"    GitHubに無い独自のコミット数  : {ahead}")
            info["behind"], info["ahead"] = behind, ahead
            if ahead != "0":
                print("    ！ 独自コミットがあるため、通常の更新(早送りマージ)ができません")

    print("\n【3】このPC内のSKILL.md(どれが実際に読まれるか)")
    reference = _clone_skill_md()
    ref_digest = _digest(reference) if info["has_clone"] else None
    if ref_digest:
        print(f"  基準(内部クローンの内容): {ref_digest}")
    all_md = _find_all_skill_md()
    info["stale"] = []
    for p in all_md:
        d = _digest(p)
        if ref_digest is None:
            mark = "  "
        elif p == reference:
            mark = "  "
        elif d == ref_digest:
            mark = "OK"
        else:
            mark = "！ "
            info["stale"].append(p)
        print(f"  {mark} {d}  {p}")
    if ref_digest and info["stale"]:
        print("\n  ！ が付いた場所が、内部クローンと違う(古い)内容です")

    print("\n【4】キャッシュのバージョンフォルダ")
    if CACHE_ROOT.is_dir():
        for v in sorted(CACHE_ROOT.iterdir()):
            if v.is_dir():
                print(f"    {v.name}")
    else:
        print("    キャッシュフォルダがありません")

    return info


def print_verdict(info: dict) -> None:
    print("\n" + "=" * 70)
    if not info.get("has_clone"):
        print("判定: マーケットプレイス経由ではないため、この仕組みでの更新対象外です。")
    elif info.get("fetch_ok") is False:
        print("判定: GitHubに接続できていません。ネットワークと認証を確認してください。")
    elif info.get("ahead", "0") != "0" or info.get("dirty"):
        print("判定: 内部クローンが通常の方法では更新できない状態です。")
        print("      → `python doctor.py --repair` で強制的に揃えてください。")
    elif info.get("behind", "0") != "0":
        print("判定: GitHubより古い状態です。")
        print("      → `python doctor.py --repair` で最新にできます。")
    elif info.get("stale"):
        print("判定: 内部クローンは最新ですが、実際に読まれるキャッシュが古いままです。")
        print("      → `python doctor.py --repair` でキャッシュへ反映してください。")
    else:
        print("判定: 最新の状態です。")
        print("      これでも動きが変わらない場合は、セッションを開き直してください")
        print("      (既に開いているセッションには反映されません)。")
    print("=" * 70)


def repair() -> None:
    print("\n" + "=" * 70)
    print("最新の内容に強制的に揃えます")
    print("=" * 70)

    if not (MARKETPLACE_DIR / ".git").is_dir():
        print("マーケットプレイス経由ではないため、行う修復はありません。")
        return

    if _run(["git", "fetch", "origin"], MARKETPLACE_DIR).returncode != 0:
        print("！ GitHubから取得できませんでした。ネットワークと認証を確認してください。")
        return

    # 早送りできない状態(独自コミットや残った変更)でも確実に揃えるため、
    # 内部クローンをGitHub上の内容に合わせる。ここは取得用の複製であり、
    # 利用者が編集する場所ではないため、失われて困る内容は無い。
    reset = _run(["git", "reset", "--hard", "origin/main"], MARKETPLACE_DIR)
    if reset.returncode != 0:
        print(f"！ 内部クローンを揃えられませんでした: {reset.stderr.strip()[:200]}")
        return
    print(f"  内部クローンを揃えました: {_run(['git', 'log', '--oneline', '-1'], MARKETPLACE_DIR).stdout.strip()}")

    src = MARKETPLACE_DIR / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
    if not src.is_dir():
        print(f"！ 取得した内容の中にスキルが見つかりません: {src}")
        return
    if not CACHE_ROOT.is_dir():
        print("  キャッシュフォルダが無いため、コピーは行いません(次回インストール時に作られます)。")
        return

    # venvを保持したまま入れ替える処理は更新スクリプトと共通
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import refresh_marketplace_cache as refresh

    for version_dir in sorted(CACHE_ROOT.iterdir()):
        if not version_dir.is_dir():
            continue
        dest = version_dir / "skills" / PLUGIN_NAME
        if dest.is_dir():
            refresh._replace_skill_dir(src, dest)
        else:
            import shutil
            shutil.copytree(src, dest)
        print(f"  反映しました: {dest}")

    print("\n完了しました。**新しいセッションを開始**すると反映されます")
    print("(いま開いているセッションの内容は入れ替わりません)。")


def main() -> None:
    parser = argparse.ArgumentParser(description="スキルが最新の内容で動く状態か調べ、必要なら直す")
    parser.add_argument("--repair", action="store_true", help="最新の内容に強制的に揃える")
    args = parser.parse_args()

    if args.repair and _relaunch_outside_cache_if_needed():
        return

    info = diagnose()
    if args.repair:
        repair()
    else:
        print_verdict(info)


if __name__ == "__main__":
    main()
