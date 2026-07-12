"""Batch / agent-as-LLM client — for running inside Claude Code (Cowork).

Inside a Cowork session the natural "LLM" is the Claude Code agent itself, not a
separate API key. A subprocess can't synchronously call back up into the agent
mid-loop, so the three bounded LLM touchpoints (relevance, extraction, scoring)
are fulfilled by a **file handoff**:

    plan  : run the stages with this client in *collect* mode. Every LLM call
            whose answer isn't already cached is written to ``requests.jsonl``
            (keyed by a stable ``cache_key``, e.g. the paper id) and a stub is
            returned so the stage can proceed on a throwaway DB snapshot.
    answer: the agent reads ``requests.jsonl``, produces the structured answer
            for each (it *is* the model), and appends ``{key, payload}`` lines to
            ``answers.jsonl``.
    apply : run the stages for real with this client in *strict* mode. Every LLM
            call now hits the cache; a miss raises rather than committing a stub.

Because keys are content-stable (tied to the paper, not the exact prompt text),
the loop converges: plan surfaces one stage's requests per round, the agent
answers them, and the next plan round advances to the following stage.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .base import LLMClient, T, build_stub


class MissingBatchAnswer(BaseException):
    """Raised in strict (apply) mode when a request has no cached answer.

    Derives from ``BaseException`` (not ``Exception``) on purpose: it is a
    control signal meaning "the plan/answer loop isn't finished", and it must not
    be swallowed by the broad ``except Exception`` guards inside stages (e.g. the
    extractor's recovery path). It propagates up to ``batch-apply``.
    """

    def __init__(self, key: str) -> None:
        super().__init__(f"No batched answer for request {key!r}; run `batch-plan` and answer it first.")
        self.key = key


class BatchLLM(LLMClient):
    def __init__(self, batch_dir: str | Path, *, strict: bool = False) -> None:
        self.dir = Path(batch_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.requests_path = self.dir / "requests.jsonl"
        self.answers_path = self.dir / "answers.jsonl"
        self.strict = strict
        self._answers: dict[str, Any] = _load_answers(self.answers_path)
        self.pending: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0

    # -- keying ----------------------------------------------------------- #
    @staticmethod
    def _key(schema_name: str, prompt: str, cache_key: str | None) -> str:
        base = cache_key if cache_key else hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        return f"{schema_name}:{base}"

    # -- LLMClient -------------------------------------------------------- #
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        cache_key: str | None = None,
    ) -> str:
        key = self._key("text", prompt, cache_key)
        if key in self._answers:
            self.hits += 1
            return str(self._answers[key])
        self.misses += 1
        if self.strict:
            raise MissingBatchAnswer(key)
        self._record(key, "text", None, prompt, system)
        return ""

    def structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 2048,
        temperature: float = 0.0,
        cache_key: str | None = None,
    ) -> T:
        key = self._key(schema.__name__, prompt, cache_key)
        if key in self._answers:
            try:
                out = schema.model_validate(self._answers[key])
                self.hits += 1
                return out
            except Exception:
                # A cached answer that no longer validates counts as a miss.
                if self.strict:
                    raise MissingBatchAnswer(key) from None
        else:
            if self.strict:
                raise MissingBatchAnswer(key)
        self.misses += 1
        self._record(key, schema.__name__, schema, prompt, system)
        return build_stub(schema)

    # -- request collection ---------------------------------------------- #
    def _record(
        self, key: str, schema_name: str, schema: type[Any] | None, prompt: str, system: str | None
    ) -> None:
        rec: dict[str, Any] = {"key": key, "schema": schema_name, "prompt": prompt}
        if system:
            rec["system"] = system
        if schema is not None:
            rec["json_schema"] = schema.model_json_schema()
        self.pending[key] = rec

    def flush_requests(self) -> int:
        """Write pending requests to ``requests.jsonl`` (overwrite). Return count."""
        lines = [json.dumps(rec) for rec in self.pending.values()]
        self.requests_path.write_text("\n".join(lines) + ("\n" if lines else ""))
        return len(self.pending)

    def clear_requests(self) -> None:
        self.requests_path.write_text("")


# --------------------------------------------------------------------------- #
# File helpers (used by the CLI and by tests simulating the agent's answers)
# --------------------------------------------------------------------------- #
def _load_answers(path: Path) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    if not path.exists():
        return answers
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        answers[rec["key"]] = rec["payload"]
    return answers


def read_requests(batch_dir: str | Path) -> list[dict[str, Any]]:
    """Read the pending request records the agent needs to answer."""
    path = Path(batch_dir) / "requests.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def append_answer(batch_dir: str | Path, key: str, payload: Any) -> None:
    """Append one ``{key, payload}`` answer line (idempotent-ish; last wins)."""
    path = Path(batch_dir) / "answers.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps({"key": key, "payload": payload}) + "\n")
