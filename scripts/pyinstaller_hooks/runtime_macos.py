"""Bootstrap native dependencies before every GUI or headless worker entry."""
from core.macos_runtime import bootstrap

bootstrap()
