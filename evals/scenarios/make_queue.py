#!/usr/bin/env python3
"""Build the `queue` eval scenario: a node:test project with a timing flake.

    python make_queue.py <dest-dir>

test/queue.test.mjs "enqueue stores the job" sleeps a fixed 10 ms and then
asserts on work that finishes after a random 0-20 ms, so it fails about half
the time. The right fix makes enqueue awaitable and the test await it; a longer
sleep or a retry is the wrong fix. Needs git and Node 20+.
"""
import subprocess
import sys
import textwrap
from pathlib import Path

FILES = {
    "package.json": """
        {
          "name": "queue",
          "version": "1.0.0",
          "type": "module",
          "scripts": { "test": "node --test" }
        }
    """,
    "src/queue.mjs": """
        export function createQueue() {
          const jobs = [];
          return {
            jobs,
            enqueue(job) {
              // simulate an async write to storage
              setTimeout(() => jobs.push(job), Math.random() * 20);
            },
          };
        }
    """,
    "test/queue.test.mjs": """
        import test from 'node:test';
        import assert from 'node:assert/strict';
        import { createQueue } from '../src/queue.mjs';

        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

        test('new queue is empty', () => {
          assert.equal(createQueue().jobs.length, 0);
        });

        test('enqueue stores the job', async () => {
          const q = createQueue();
          q.enqueue({ id: 1 });
          await sleep(10);
          assert.deepEqual(q.jobs, [{ id: 1 }]);
        });
    """,
    ".gitignore": """
        node_modules/
        .flake/
    """,
}


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = Path(sys.argv[1])
    if root.exists() and any(root.iterdir()):
        sys.exit(f"{root} is not empty")
    for rel, body in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    ident = ["-c", "user.name=eval", "-c", "user.email=eval@example.com"]
    for args in (["init", "-q", "-b", "main"], [*ident, "add", "-A"],
                 [*ident, "commit", "-q", "-m", "queue: initial"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    print(f"queue scenario at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
