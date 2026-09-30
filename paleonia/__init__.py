"""PaleonIA — transcrição de manuscritos.

Módulos: api, image_enhance, segment, reading, session, vectors, db.
"""

from paleonia.config import get_settings, load_env

load_env()

__version__ = get_settings().app_version
