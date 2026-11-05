from common.db import Base
from common.migrations import configure_migrations
from services.ledger.app import models
from services.ledger.app.config import get_settings


configure_migrations(get_settings().database_url, Base.metadata)
