from alembic import op

from common.db import Base
from common.events import PendingEvent
from services.external.app import models


revision = "external_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
