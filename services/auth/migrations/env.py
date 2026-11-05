from common.db import Base
from common.migrations import configure_migrations
from services.auth.app import models
from services.auth.app.config import get_settings


configure_migrations(get_settings().database_url, Base.metadata)
