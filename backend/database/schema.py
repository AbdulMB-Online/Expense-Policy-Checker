"""Versioned SQLite schema and initial demo accounts."""

SCHEMA_VERSION = 1
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
DEMO_USERS = (
    ("employee-anika", "Anika Rao", "employee"),
    ("employee-karan", "Karan Mehta", "employee"),
    ("employee-rohan", "Rohan Desai", "employee"),
    ("employee-lucia", "Lucía Torres", "employee"),
    ("employee-mei", "Mei Tan", "employee"),
    ("employee-kavya", "Kavya Iyer", "employee"),
    ("employee-yusuf", "Yusuf Khan", "employee"),
    ("employee-elena", "Elena Brooks", "employee"),
    ("employee-amina", "Amina Rahman", "employee"),
    ("employee-rafael", "Rafael Costa", "employee"),
    ("employee-chloe", "Chloë D’Souza", "employee"),
    ("employee-min", "Min Park", "employee"),
    ("reviewer-finance", "Morgan Finance", "reviewer"),
    ("reviewer-backup", "Taylor Finance", "reviewer"),
)

SCHEMA = (
    """CREATE TABLE users (
        id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
        role TEXT NOT NULL CHECK(role IN ('employee','reviewer'))
    )""",
    """CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
        expires_at INTEGER NOT NULL
    )""",
    """CREATE TABLE artifacts (
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL,
        media_type TEXT NOT NULL, contents BLOB NOT NULL, size INTEGER NOT NULL,
        sha256 TEXT NOT NULL, uploaded_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        CHECK(size = length(contents)), CHECK(kind != 'receipt' OR size <= 5242880)
    )""",
    """CREATE TABLE policy_versions (
        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
        body TEXT NOT NULL, artifact_id TEXT NOT NULL REFERENCES artifacts(id)
    )""",
    """CREATE TABLE datasets (
        id TEXT PRIMARY KEY, expense_key TEXT NOT NULL,
        expense_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
        policy_id TEXT NOT NULL REFERENCES policy_versions(id),
        policy_artifact_id TEXT NOT NULL REFERENCES artifacts(id),
        parsed TEXT NOT NULL, created_by TEXT REFERENCES users(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )""",
    """CREATE TABLE expenses (
        id TEXT PRIMARY KEY, scope TEXT NOT NULL, external_id TEXT NOT NULL,
        origin TEXT NOT NULL CHECK(origin IN ('file','submission')),
        owner_id TEXT REFERENCES users(id), created_by TEXT REFERENCES users(id),
        request_id TEXT, fingerprint TEXT, revision INTEGER NOT NULL DEFAULT 1,
        record TEXT NOT NULL, receipt_id TEXT REFERENCES artifacts(id),
        UNIQUE(scope,external_id), UNIQUE(scope,created_by,request_id)
    )""",
    """CREATE TABLE expense_revisions (
        id TEXT PRIMARY KEY, expense_id TEXT NOT NULL REFERENCES expenses(id),
        revision INTEGER NOT NULL, record TEXT NOT NULL,
        owner_id TEXT REFERENCES users(id), receipt_id TEXT REFERENCES artifacts(id),
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(expense_id,revision)
    )""",
    """CREATE TABLE check_runs (
        id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
        dataset_id TEXT NOT NULL REFERENCES datasets(id),
        scope TEXT NOT NULL, policy_id TEXT NOT NULL REFERENCES policy_versions(id),
        engine_version TEXT NOT NULL, errors TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )""",
    """CREATE TABLE check_results (
        run_id TEXT NOT NULL REFERENCES check_runs(id),
        revision_id TEXT NOT NULL REFERENCES expense_revisions(id),
        position INTEGER NOT NULL, findings TEXT NOT NULL,
        PRIMARY KEY(run_id,revision_id)
    )""",
    """CREATE TABLE review_events (
        id INTEGER PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES expense_revisions(id),
        run_id TEXT NOT NULL REFERENCES check_runs(id),
        reviewer_id TEXT NOT NULL REFERENCES users(id),
        decision TEXT NOT NULL CHECK(decision IN ('approved','rejected','changes_requested')),
        comment TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(revision_id)
    )""",
    """CREATE TABLE exports (
        artifact_id TEXT PRIMARY KEY REFERENCES artifacts(id),
        run_id TEXT NOT NULL REFERENCES check_runs(id),
        user_id TEXT NOT NULL REFERENCES users(id), filters TEXT NOT NULL
    )""",
    "CREATE INDEX expenses_scope_owner ON expenses(scope,owner_id)",
    "CREATE INDEX results_revision ON check_results(revision_id)",
    "CREATE INDEX datasets_created ON datasets(created_at)",
)
