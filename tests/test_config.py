"""Config loading + the `extends:` deep-merge feature."""

from __future__ import annotations

from research_agent.config import Config, _deep_merge


def test_deep_merge_recurses_dicts_and_overrides_scalars():
    base = {"a": 1, "nested": {"x": 1, "y": 2}, "list": [1, 2]}
    override = {"a": 2, "nested": {"y": 3, "z": 4}, "list": [9]}
    merged = _deep_merge(base, override)
    assert merged == {"a": 2, "nested": {"x": 1, "y": 3, "z": 4}, "list": [9]}


def test_extends_merges_over_base(tmp_path):
    base = tmp_path / "base.yaml"
    base.write_text(
        "name: base\n"
        "problem_statement: solve X\n"
        "seed_papers: ['1', '2']\n"
        "llm: {provider: anthropic}\n"
        "storage: {db_path: data/base.db}\n"
    )
    child = tmp_path / "child.yaml"
    child.write_text(
        "extends: base.yaml\n"
        "llm: {provider: batch, batch_dir: state/batch}\n"
        "storage: {db_path: state/x.db}\n"
    )
    cfg = Config.load(child)
    # Inherited from base:
    assert cfg.name == "base"
    assert cfg.problem_statement == "solve X"
    assert cfg.seed_papers == ["1", "2"]
    # Overridden by child (dict merge, not replace):
    assert cfg.llm.provider == "batch"
    assert cfg.llm.batch_dir == "state/batch"
    assert cfg.storage.db_path == "state/x.db"


def test_hexgen_nightly_config_loads():
    cfg = Config.load("config/hexgen-nightly.yaml")
    assert cfg.name == "hexgen"  # inherited
    assert cfg.llm.provider == "batch"  # overridden
    assert cfg.storage.db_path == "state/hexgen.db"
    assert cfg.seed_papers and cfg.problem_statement  # inherited content present
