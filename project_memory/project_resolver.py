import os
from pathlib import Path

from project_memory.schemas import ProjectContext


PROJECT_ROOT_ENV = "PROJECT_MEMORY_ROOT"


def resolve_project_context(
    root_path: str | Path | None = None,
) -> ProjectContext:
    """
    Aktif projenin adını ve kök klasörünü belirler.

    Öncelik sırası:
    1. Fonksiyona verilen root_path
    2. PROJECT_MEMORY_ROOT ortam değişkeni
    3. Terminalin mevcut çalışma klasörü
    """

    if root_path is not None:
        project_path = Path(root_path)
    else:
        environment_path = os.getenv(PROJECT_ROOT_ENV)

        if environment_path:
            project_path = Path(environment_path)
        else:
            project_path = Path.cwd()

    # Yolu mutlak ve standart hale getirir.
    project_path = project_path.expanduser().resolve()

    if not project_path.exists():
        raise FileNotFoundError(
            f"Proje klasörü bulunamadı: {project_path}"
        )

    if not project_path.is_dir():
        raise NotADirectoryError(
            f"Verilen yol bir klasör değil: {project_path}"
        )

    if not project_path.name:
        raise ValueError(
            f"Proje adı klasör yolundan belirlenemedi: {project_path}"
        )

    return ProjectContext(
        name=project_path.name,
        root_path=str(project_path),
    )