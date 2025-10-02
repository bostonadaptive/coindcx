"""Untrack already-committed __pycache__ and .pyc files from git and stage .gitignore changes."""
import os
import subprocess

root = os.path.dirname(os.path.dirname(__file__))
removed = []
for dirpath, dirnames, filenames in os.walk(root):
    for name in filenames:
        if name.endswith('.pyc'):
            fp = os.path.join(dirpath, name)
            try:
                subprocess.run(['git', 'rm', '--cached', '-f', fp], check=True)
                removed.append(fp)
            except Exception:
                pass
    for d in list(dirnames):
        if d == '__pycache__':
            fp = os.path.join(dirpath, d)
            try:
                subprocess.run(['git', 'rm', '-r', '--cached', '-f', fp], check=True)
                removed.append(fp)
            except Exception:
                pass
print('Untracked', len(removed), 'files/dirs')
