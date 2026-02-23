"""
One-time script: Remove dead code from seerr/background_tasks.py.

After rewriting check_show_subscriptions(), ~330 lines of the old implementation
were left in the file (from the line after "Completed show subscription check."
until "async def search_individual_episodes"). This script deletes that block
so the file is valid and the next function follows the log line.

Run from repo root: python scripts/remove_subscription_dead_code.py
"""
import os

path = os.path.join(os.path.dirname(__file__), '..', 'seerr', 'background_tasks.py')
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

start = None
end = None
for i, line in enumerate(lines):
    if 'Completed show subscription check.' in line and start is None:
        start = i + 1
    if start is not None and 'async def search_individual_episodes' in line:
        end = i
        break

if start is not None and end is not None:
    new_lines = lines[:start] + lines[end:]
    with open(path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    print('Removed lines %d to %d (%d lines)' % (start + 1, end, end - start))
else:
    print('Could not find markers: start=%s end=%s' % (start, end))
