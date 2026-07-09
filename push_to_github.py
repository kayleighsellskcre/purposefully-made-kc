import subprocess, os, sys

REPO = r"C:\Users\Kayle\OneDrive\Desktop\kb_apparel_site"
LOG  = r"C:\Users\Kayle\push_log.txt"

def run(cmd):
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return r.stdout.strip() + ("\n" + r.stderr.strip() if r.stderr.strip() else ""), r.returncode

lines = []

out, rc = run(["git", "add", "-A"])
lines.append(f"git add -A (rc={rc}):\n{out}\n")

out, rc = run(["git", "status", "--short"])
lines.append(f"git status (rc={rc}):\n{out}\n")

out, rc = run(["git", "commit", "-m",
               "Fix: product delete button event delegation + CSRF exemptions for admin routes"])
lines.append(f"git commit (rc={rc}):\n{out}\n")

out, rc = run(["git", "push", "origin", "main"])
lines.append(f"git push (rc={rc}):\n{out}\n")

with open(LOG, "w") as f:
    f.write("\n".join(lines))

print("Done — see", LOG)
