from common.db import make_engine, make_session_factory, session_dependency
from services.payments.app.config import get_settings


settings = get_settings()
engine = make_engine(settings)
session_factory = make_session_factory(engine)
get_session = session_dependency(session_factory)
