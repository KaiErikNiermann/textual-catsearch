"""A running TypeScript port to ask cases of: ``js/test/harness/oracle.ts`` over a pipe."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final, Self

__all__ = ["ORACLE", "Oracle", "OracleError", "node"]

ORACLE: Final = Path(__file__).resolve().parents[2] / "js" / "test" / "harness" / "oracle.ts"


class OracleError(RuntimeError):
    """The port threw on a case, or the process died."""


def node() -> str | None:
    """The ``node`` to run the oracle with: ``$CATSEARCH_NODE``, else the one on ``PATH``."""
    return os.environ.get("CATSEARCH_NODE") or shutil.which("node")


class Oracle:
    """One long-lived oracle process; ask it cases one at a time."""

    def __init__(self, executable: str) -> None:
        self._proc = subprocess.Popen(  # noqa: S603 — a fixed script, not user input
            [executable, str(ORACLE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            # A case may carry a lone surrogate, which only survives the pipe escaped.
            errors="strict",
            cwd=ORACLE.parents[2],
        )

    def ask(self, case: dict[str, Any]) -> Any:
        stdin, stdout = self._proc.stdin, self._proc.stdout
        if stdin is None or stdout is None:
            raise OracleError("oracle has no pipes")
        stdin.write(json.dumps(case, ensure_ascii=True) + "\n")
        stdin.flush()
        line = stdout.readline()
        if not line:
            raise OracleError(f"oracle exited with {self._proc.wait()}")
        answer: dict[str, Any] = json.loads(line)
        if "error" in answer:
            raise OracleError(f"{case!r}\n{answer['error']}")
        return answer["ok"]

    def close(self) -> None:
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc.wait(timeout=10)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
