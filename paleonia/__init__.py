"""PaleonIA — transcrição de manuscritos."""

from paleonia.config import get_settings, load_env

load_env()

__version__ = get_settings().app_version
