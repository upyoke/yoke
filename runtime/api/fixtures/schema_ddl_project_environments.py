"""Project site/environment rows shared by disposable Postgres fixtures."""

_PROJECT_ENVIRONMENT_DDL = """
CREATE TABLE IF NOT EXISTS sites (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS environments (
    id TEXT PRIMARY KEY,
    site TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT,
    health_check_url TEXT,
    last_deployed_at TEXT,
    created_at TEXT NOT NULL,
    settings TEXT DEFAULT '{}',
    UNIQUE(site, name)
);
INSERT INTO sites(id,project_id,name,created_at)
VALUES ('yoke-api',1,'Yoke API','2026-01-01T00:00:00Z')
ON CONFLICT(id) DO NOTHING;
INSERT INTO environments(id,site,name,created_at)
VALUES ('yoke-api-development','yoke-api','development','2026-01-01T00:00:00Z')
ON CONFLICT(id) DO NOTHING;
INSERT INTO sites(id,project_id,name,created_at)
VALUES ('externalwebapp-api',2,'External webapp API','2026-01-01T00:00:00Z')
ON CONFLICT(id) DO NOTHING;
INSERT INTO environments(id,site,name,created_at)
VALUES (
    'externalwebapp-api-development',
    'externalwebapp-api',
    'development',
    '2026-01-01T00:00:00Z'
)
ON CONFLICT(id) DO NOTHING;
"""

__all__ = ["_PROJECT_ENVIRONMENT_DDL"]
