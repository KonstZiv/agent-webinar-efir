import re
from pathlib import Path

from app.settings import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "env.example"


def test_env_example_lists_every_setting_without_values() -> None:
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assignments = [line for line in lines if re.match(r"^[A-Z][A-Z0-9_]*=", line)]

    names = {line.split("=", 1)[0] for line in assignments}
    assert names == {name.upper() for name in Settings.model_fields} | {"PORT"}
    assert all(line.endswith("=") for line in assignments), "values must stay empty"
