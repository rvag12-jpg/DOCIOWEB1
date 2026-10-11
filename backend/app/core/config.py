import os
from dataclasses import dataclass
from pathlib import Path


def _csv(value: str) -> list[str]:
    return [x.strip() for x in value.split(',') if x.strip()]


def _enabled(value: str) -> bool:
    return value.strip().lower() in ('true', '1', 'yes')


_demo_mode = _enabled(os.getenv('DOCIO_DEMO_MODE', 'false'))
_base_data_dir = Path(os.getenv('DOCIO_DATA_DIR', 'data'))


@dataclass(frozen=True)
class Settings:
    demo_mode: bool = _demo_mode
    api_prefix: str = os.getenv('DOCIO_API_PREFIX', '/api/v1')
    data_dir: Path = (_base_data_dir / 'demo' if _demo_mode else _base_data_dir).resolve()
    pdf_dpi: int = int(os.getenv('DOCIO_PDF_DPI', '160'))
    max_upload_mb: int = int(os.getenv('DOCIO_MAX_UPLOAD_MB', '100'))
    cors_origins: tuple[str, ...] = tuple(_csv(os.getenv('DOCIO_CORS_ORIGINS', 'http://localhost:5173')))


settings = Settings()
