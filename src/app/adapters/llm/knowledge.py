"""The knowledge base of the draft: docs/course.md, whole, and nothing else."""

from pathlib import Path

COURSE_FILE = "course.md"


def read_knowledge(docs_dir: Path) -> str:
    """The text of ``course.md``; the file is read from the working directory's ``docs/``."""
    path = docs_dir / COURSE_FILE
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise RuntimeError(
            f"Knowledge base not found: {path} (docs/ is read from the working directory)"
        ) from error
