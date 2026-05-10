"""Compatibility checks for shipped Copilot runtime customizations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "src" / "voronoi" / "data"
AGENTS_DIR = DATA_DIR / "agents"
SKILLS_DIR = DATA_DIR / "skills"
SCRIPTS_DIR = DATA_DIR / "scripts"


REQUIRED_AGENT_KEYS = {
    "name",
    "description",
    "tools",
    "disable-model-invocation",
    "user-invocable",
}
REQUIRED_SKILL_KEYS = {
    "name",
    "description",
    "disable-model-invocation",
    "user-invocable",
}
BOOLEAN_KEYS = {"disable-model-invocation", "user-invocable"}
STALE_RUNTIME_TERMS = (
    "user-invokable",
    "Build/Investigate/Explore/Hybrid",
    "Investigate/Explore/Hybrid",
    "hybrid-mode",
    "RIGOR:<standard|analytical|scientific|experimental>",
)


def _frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    assert lines and lines[0] == "---", f"{path} is missing YAML frontmatter"
    try:
        end = lines[1:].index("---") + 1
    except ValueError as exc:
        raise AssertionError(f"{path} frontmatter is not closed") from exc

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        if not line or line.startswith(" ") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip('"\'')
    return fields


def test_all_runtime_agents_have_copilot_frontmatter():
    agent_paths = sorted(AGENTS_DIR.glob("*.agent.md"))
    assert agent_paths, "runtime agents are missing"

    for path in agent_paths:
        fields = _frontmatter(path)
        missing = REQUIRED_AGENT_KEYS - fields.keys()
        assert not missing, f"{path.name} missing frontmatter keys: {sorted(missing)}"
        assert fields["name"] == path.name.removesuffix(".agent.md")
        for key in BOOLEAN_KEYS:
            assert fields[key] in {"true", "false"}, f"{path.name} has invalid {key}"
        assert "user-invokable" not in fields


def test_all_runtime_skill_directories_have_copilot_skill_entrypoint():
    skill_dirs = sorted(path for path in SKILLS_DIR.iterdir() if path.is_dir())
    assert skill_dirs, "runtime skills are missing"

    for skill_dir in skill_dirs:
        skill_path = skill_dir / "SKILL.md"
        assert skill_path.exists(), f"{skill_dir.name} is missing SKILL.md"
        fields = _frontmatter(skill_path)
        missing = REQUIRED_SKILL_KEYS - fields.keys()
        assert not missing, f"{skill_dir.name} missing frontmatter keys: {sorted(missing)}"
        assert fields["name"] == skill_dir.name
        assert len(fields["description"]) <= 1024
        for key in BOOLEAN_KEYS:
            assert fields[key] in {"true", "false"}, f"{skill_dir.name} has invalid {key}"


def test_runtime_customizations_do_not_use_stale_compatibility_terms():
    runtime_files = [
        *AGENTS_DIR.glob("*.agent.md"),
        *SKILLS_DIR.glob("*/SKILL.md"),
    ]
    assert runtime_files, "runtime customization files are missing"

    for path in runtime_files:
        text = path.read_text()
        for stale_term in STALE_RUNTIME_TERMS:
            assert stale_term not in text, f"{path.name} contains stale term {stale_term!r}"


def test_beads_runtime_guidance_uses_server_mode():
    script = (SCRIPTS_DIR / "swarm-init.sh").read_text()
    skill = (SKILLS_DIR / "beads-tracking" / "SKILL.md").read_text()

    assert "bd init --quiet --server" in script
    assert "bd init --quiet --server" in skill
    assert "do not run `bd init` inside" in skill
