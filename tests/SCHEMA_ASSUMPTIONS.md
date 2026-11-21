# What the test database assumes about production

The test database (`scripts/test_db.sh`, `tests/seed.py`) is built from the
models in the code, because the production schema isn't in the repo. Each
item below is something the tests take for granted and that only the
production database can confirm. **For the BE2-1 audit:** check each one and
note whether it matches.

## What the tests can and can't prove

- **Can prove:** the refactor didn't change behaviour. The old code and the
  new code run against the same test database and must give identical
  responses, emails and flows.
- **Can't prove:** that behaviour matches the live site wherever it depends on
  the schema. If the test schema differs from production, the old and new
  code are both being checked against the wrong schema.

## Adjusted by hand in the seed (the models alone can't build these)

| # | Assumption | Why | If production differs |
|---|---|---|---|
| A1 | `registered_users.createCount` has `DEFAULT 0` | Validated users are inserted without a createCount, and only 0 may create a profile. The live site works, so production must have this default. | New teachers couldn't create profiles. |
| A2 | `password_reset_tokens.token` is a limited-length string (test uses `VARCHAR(255)`) with a unique index | SQL Server can't index `VARCHAR(max)`, so the model's `unique=True` can't be built as written. | The reset flow may behave differently on duplicates. |

## Taken from the models as written

| # | Assumption | Production may instead have | What would change |
|---|---|---|---|
| B1 | Text columns with no length are `VARCHAR(max)` | `TEXT`/`NTEXT` (the 85 `cast(..., String)` calls suggest this) or `NVARCHAR` | Queries that don't cast (for example `DISTINCT` on `schools`) would fail on `TEXT`. `VARCHAR` vs `NVARCHAR` changes how non-English characters are stored. |
| B2 | `schools.*` columns are comparable without a cast | `TEXT` columns | The location dropdown routes would error. |
| B3 | Forum tables have foreign keys: `forum_posts.user_id`, `forum_comments.post_id/user_id/parent_comment_id` and `post_votes.post_id/user_id`, none with `ON DELETE CASCADE` | No foreign keys, or cascading ones | **The "deleting a post with comments fails" finding rests on this.** Without the foreign keys the delete succeeds and leaves orphaned comments and votes. With cascade it succeeds cleanly. |
| B4 | `teacher_list.regUserID` has no foreign key | A foreign key | Deleting a user might fail instead of leaving a teacher row behind. |
| B5 | Unique constraint `uq_post_user_vote` on `(post_id, user_id)` | Missing | Double votes would be possible under concurrent requests. |
| B6 | No other unique constraints (email, url_id) | Unique constraints | Duplicate checks would be enforced by the database as well as by the code. |
| B7 | Every column is nullable except those marked `nullable=False` in the models | More `NOT NULL` columns | Some inserts the tests accept would fail live. |
| B8 | No server-side defaults other than A1. Forum `created_at` and counts are set by the app, not the database | Database defaults on other columns | Any column the app leaves unset would get a value live and `NULL` in the tests. |
| B9 | `image_data` is `VARBINARY(max)` and `last_TOD`/`created_at` are `DATETIME` | `IMAGE`, `DATETIME2` | Mostly invisible; `DATETIME2` keeps more precision. |
| B10 | Ids are `IDENTITY` starting at 1 | Same, but with existing data | Only the seeded ids matter in the tests. |
| B11 | No extra tables, columns, triggers or views that the code relies on | Any of these | Unknown. |
| B12 | `registered_users.password` and `new_users.password` hold at least 97 characters (argon2id hashes, from BE2-11) | A shorter limit (sha256_crypt hashes are about 77) | New passwords would fail to save. Login keeps working: a failed hash upgrade is logged and skipped. |
| B13 | `password_reset_tokens.token` holds at least 43 characters | Shorter | BE2-11 stores a 43-character hash, the same length as the tokens stored before, so this is unchanged. |

## Server

| # | Assumption | Production |
|---|---|---|
| C1 | SQL Server 2022 container with default collation `SQL_Latin1_General_CP1_CI_AS` (case-insensitive) | Azure SQL. The collation needs checking: email and url_id lookups depend on case-insensitivity. |

## Closing the gap

A **schema-only export** of production would let the test database be built
from it instead of from the models. That means a script of tables, columns,
types, defaults, constraints and indexes, with no data. That settles every
item above at once. It is part of BE2-1.
