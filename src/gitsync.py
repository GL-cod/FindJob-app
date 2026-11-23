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


# ------------------------------------------------------------------ updates from the original
# Each user has his own copy of the public repo. New versions are published on the original:
# the app compares its code with it, and installs it in one click (same files as the GitHub
# workflow « Mettre à jour depuis l'original »: code only, never data/ nor cdi_search.yaml).
ORIGINAL = "https://github.com/GL-cod/FindJob-app"
ORIGINAL_REF = "refs/findjob/original"
CODE_PATHS = ["app", "src", "windows", "tests", "google_sheets", ".streamlit", "requirements.txt",
              "requirements-app.txt", "cdi_search.exemple.yaml", "README.md", "INSTALLATION.md",
              "docs/index.html", ".gitignore"]
# The repos the updates come from: they never look for updates themselves.
SOURCE_REPOS = ("https://github.com/gl-cod/findjob", "https://github.com/gl-cod/findjob-app")


def original_url():
    import os
    return (os.environ.get("FINDJOB_ORIGINAL") or ORIGINAL).strip().rstrip("/")


def is_source_repo(root):
    return repo_url(root).lower() in SOURCE_REPOS


def code_differences(root, ref):
    """[(status, path)] of code files that differ between this copy and `ref` (A = new file)."""
    ok, out = git(root, "diff", "--no-renames", "--name-status", "HEAD", ref, "--", *CODE_PATHS)
    if not ok:
        return []
    return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]


def check_original(root, url=None):
    """Is a new version published on the original? Returns None (can't tell: offline, source
    repo...) or {"available": bool, "files": n, "date": "24/11 à 00h50"}."""
    if is_source_repo(root):
        return None
    url = url or original_url()
    ok, _ = git(root, "fetch", "--quiet", "--depth", "1", "--no-tags", url, f"+main:{ORIGINAL_REF}", timeout=60)
    if not ok:
        return None
    files = code_differences(root, ORIGINAL_REF)
    ok, date = git(root, "log", "-1", "--format=%cd", "--date=format:%d/%m à %Hh%M", ORIGINAL_REF)
    return {"available": bool(files), "files": len(files), "date": date.strip() if ok else ""}


def install_original(root, url=None):
    """Copy the original's code into this copy, commit it and push it to the user's GitHub repo
    (so the GitHub searches run the new code too). Returns (ok, message)."""
    url = url or original_url()
    pull(root)
    ok, out = git(root, "fetch", "--quiet", "--depth", "1", "--no-tags", url, f"+main:{ORIGINAL_REF}", timeout=120)
    if not ok:
        return False, f"impossible de joindre {url} : {out}"
    changes = code_differences(root, ORIGINAL_REF)
    if not changes:
        return True, "déjà à jour"
    removed = [p for st, p in changes if st.startswith("D")]
    kept = [p for st, p in changes if not st.startswith("D")]
    if removed:
        git(root, "rm", "-q", "--", *removed)
    if kept:
        ok, out = git(root, "checkout", ORIGINAL_REF, "--", *kept)
        if not ok:
            return False, out
    ok, out = git(root, *WHO, "commit", "-q", "-m", f"Mise à jour du code depuis {url} [skip ci]")
    if not ok:
        return False, out
    for _ in range(3):
        ok, out = git(root, "push", "origin", "HEAD:main")
        if ok:
            return True, f"{len(changes)} fichier(s) mis à jour"
        git(root, "pull", "--rebase", "origin", "main")
    return True, ("mise à jour installée sur ce PC, mais pas encore envoyée sur GitHub "
                  f"(elle partira au prochain envoi) : {out[-200:]}")


if __name__ == "__main__":
    ok, out = pull(Path(__file__).resolve().parent.parent)
    print(("git: " if ok else "git ERROR: ") + out)
    sys.exit(0 if ok else 1)
