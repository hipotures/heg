# Database Migrations

## Procedure

1. Identify current `PRAGMA user_version`.
2. Add the smallest additive migration.
3. Update schema version exactly once.
4. Create an SQLite Online Backup of a previous-version workspace.
5. Run migration on the backup first.
6. Run integrity and foreign-key checks.
7. Compare canonical historical rows/fingerprints before and after.
8. Test fresh database creation.
9. Test reopening and relevant runtime queries.
10. Update schema reference and implementation status.

## Rules

- Do not edit historical migration files after release.
- Keep new columns nullable/defaulted when preserving historical rows.
- Never rewrite historical reports or attempt outcomes to fit a new schema.
- Avoid using physical database file hashes under WAL as scientific identity.
- Add indexes only for measured query paths.
- Preserve one authoritative writer.

## Required evidence

```sql
PRAGMA user_version;
PRAGMA integrity_check;
PRAGMA foreign_key_check;
```

For a migration touching plan fields, prove historical plan fingerprints
recompute exactly.

For a migration touching candidate/verification references, prove FK and
pin/delete semantics.

For attempt/memory changes, prove Resume from the migrated database.
