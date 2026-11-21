"""Database engine and sessions (BE2-4).

Route handlers take a session with `db: Session = Depends(get_db)`; it is
closed when the request finishes, even on errors. Code that runs outside
a request (the scheduled jobs) opens its own with SessionLocal().
"""
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from config import settings

database_url = URL.create(
    "mssql+pyodbc",
    username=settings.database_uid,
    password=settings.database_password,  # URL.create escapes @, / and :
    host=settings.database_server,
    port=settings.database_port,
    database=settings.database_name,
    query={"driver": settings.database_driver, **settings.database_options},
)

# pool_pre_ping checks a pooled connection before use, so the first request
# after Azure SQL drops an idle connection doesn't fail.
engine = create_engine(database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
