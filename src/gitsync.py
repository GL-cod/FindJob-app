"""Small git helpers for the local app (pull updates, push the user's feedback file).

Everything in the repo is written by GitHub Actions or by Claude, except data/feedback.json,
which only this PC writes. So when a pull cannot be replayed cleanly, the safe recovery is:
abort whatever is in progress, keep the local feedback file, and align on origin/main.
Run `python -m src.gitsync` to update from a script (windows/run_linkedin.ps1).
"""
import subprocess
import sys
from pathlib import Path

WHO = ["-c", "user.name=Mes candidatures", "-c", "user.email=mes-candidatures@users.noreply.github.com"]
LOCAL_FILES = ["data/feedback.json"]   # only written on this PC: local copy always wins


def git(root, *args, timeout=120):
    try:
        r = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return False, str(e)


def abort_in_progress(root):
    """Leave any half-done rebase / cherry-pick / merge (they block every later pull)."""
    for args in (("rebase", "--abort"), ("cherry-pick", "--abort"), ("merge", "--abort")):
        git(root, *args)


def ensure_on_main(root):
    """A stuck rebase can leave HEAD detached: put the clone back on its main branch, same commit."""
    on_branch, _ = git(root, "symbolic-ref", "-q", "HEAD")
    if not on_branch:
        git(root, "checkout", "-B", "main")
        git(root, "branch", "--set-upstream-to=origin/main", "main")


def pull(root):
    abort_in_progress(root)
    ensure_on_main(root)
    ok, out = git(root, "pull", "--rebase", "--autostash", "origin", "main")
    if ok:
        return True, out
    # Could not replay local commits: keep the local-only files, align on GitHub, put them back.
    abort_in_progress(root)
    saved = {}
    for rel in LOCAL_FILES:
        p = Path(root) / rel
        if p.exists():
            saved[rel] = p.read_bytes()
    ok_fetch, out_fetch = git(root, "fetch", "origin", "main")
    if not ok_fetch:
        return False, out_fetch
    ok_reset, out_reset = git(root, "checkout", "-B", "main", "origin/main")
    if ok_reset:
        ok_reset, out_reset = git(root, "reset", "--hard", "origin/main")
    for rel, data in saved.items():
        (Path(root) / rel).write_bytes(data)
    return ok_reset, f"recovered after a failed pull: {out}\n{out_reset}"


def repo_url(root):
    """https://github.com/<owner>/<repo> of this clone (each user has his own copy)."""
    ok, out = git(root, "remote", "get-url", "origin")
    url = out.strip() if ok else ""
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:"):]
    url = url.removesuffix(".git").rstrip("/")
    return url if url.startswith("https://github.com/") else "https://github.com"


def head(root):
    ok, out = git(root, "rev-parse", "HEAD")
    return out.strip() if ok else ""


DATA_PREFIXES = ("data/", "docs/")   # written by the watchers: not an app update


def code_changed(root, before, after):
    """True when the commits between `before` and `after` touch the app itself (not just offers)."""
    if not before or not after or before == after:
        return False
    ok, out = git(root, "diff", "--name-only", before, after)
    if not ok:
        return True
    return any(f and not f.startswith(DATA_PREFIXES) for f in out.splitlines())


def last_update(root):
    """Date of the last change to the app's code (for « Version du ... »)."""
    ok, out = git(root, "log", "-1", "--format=%cd", "--date=format:%d/%m à %Hh%M", "--",
                  "app", "src", "windows", "requirements.txt", "requirements-app.txt")
    return out.strip() if ok else ""


def push_file(root, relpath, message):
    """Commit one file (if it changed) and push it; also pushes an earlier commit that failed to go out."""
    abort_in_progress(root)
    git(root, "add", relpath)
    ok, out = git(root, *WHO, "commit", "-m", message, "--", relpath)
    if not ok and "nothing" not in out and "rien" not in out:
        return False, out
    pull(root)
    # a recovery may have dropped the local commit: commit the restored file again
    git(root, "add", relpath)
    git(root, *WHO, "commit", "-m", message, "--", relpath)
    return git(root, "push", "origin", "HEAD:main")


if __name__ == "__main__":
    ok, out = pull(Path(__file__).resolve().parent.parent)
    print(("git: " if ok else "git ERROR: ") + out)
    sys.exit(0 if ok else 1)
