from common.db import Base
from common.events import PendingEvent
from common.migrations import configure_migrations
from services.accounts.app import models
from services.accounts.app.config import get_settings


configure_migrations(get_settings().database_url, Base.metadata)
