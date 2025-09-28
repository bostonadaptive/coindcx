"""Copy existing templates into a new `templates_mcp/` folder for the MCP project variant.

Usage:
    python scripts/copy_templates_to_mcp.py

This duplicates files and preserves relative structure. It avoids copying large files like uploads.
"""
import os, shutil

SRC = os.path.join(os.path.dirname(__file__), '..', 'templates')
DST = os.path.join(os.path.dirname(__file__), '..', 'templates_mcp')

if not os.path.isdir(SRC):
    print('Templates source not found:', SRC); raise SystemExit(1)

if os.path.isdir(DST):
    print('Removing existing templates_mcp folder...')
    shutil.rmtree(DST)

print('Copying templates to', DST)
shutil.copytree(SRC, DST, ignore=shutil.ignore_patterns('*.pyc','__pycache__','*.db','instance','uploads'))
print('Done')
