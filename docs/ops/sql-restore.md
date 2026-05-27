# SQL Restore Runbook

This runbook verifies AC-12.11: an operator can restore the SQL database from a backup and have the service functional within 1 hour.

## Preconditions

- [ ] Backup file location is known and the backup file is readable.
- [ ] Backup checksum has been verified against the published checksum.
- [ ] Target database is empty, disposable, or explicitly approved for overwrite.
- [ ] Available disk space is at least 2x the backup file size.
- [ ] PostgreSQL major version matches the version used to create the backup.
- [ ] `alembic`, `pg_restore`, `psql`, `docker compose`, and `curl` are available.
- [ ] A pre-restore database snapshot exists if rollback may be required.

## Restore Steps

Set these variables before starting:

```bash
export BACKUP_FILE=/path/to/tta.dump
export DATABASE_URL=postgresql://tta:tta@localhost:5432/tta
export TARGET_DB=tta
```

1. Record the drill start time in `docs/ops/restore-drill-log.md`.
2. Stop application writers:
   ```bash
   docker compose down
   ```
3. Drop and recreate the target database:
   ```bash
   dropdb --if-exists "$TARGET_DB"
   createdb "$TARGET_DB"
   ```
4. Restore the backup:
   ```bash
   pg_restore --clean --if-exists --no-owner --dbname="$DATABASE_URL" "$BACKUP_FILE"
   ```
5. Verify migration state:
   ```bash
   alembic check
   ```
6. Start the application:
   ```bash
   docker compose up -d
   ```
7. Verify the health endpoint returns HTTP 200 within 30 seconds:
   ```bash
   curl --fail --max-time 30 http://localhost:8000/health
   ```
8. Verify at least one known test player is queryable:
   ```bash
   psql "$DATABASE_URL" -c "SELECT count(*) FROM players;"
   ```
9. Verify turn history for that player is complete:
   ```bash
   psql "$DATABASE_URL" -c "SELECT player_id, count(*) FROM turns GROUP BY player_id ORDER BY count(*) DESC LIMIT 5;"
   ```
10. Record the drill end time, elapsed minutes, success/failure, and notes in `docs/ops/restore-drill-log.md`.

## Verification Criteria

- Restore completes in 60 minutes or less.
- `alembic check` succeeds.
- The health endpoint returns HTTP 200 within 30 seconds of startup.
- At least one known test player can be queried.
- Turn history for the known player is present and complete.

## Rollback Procedure

If restore or verification fails:

1. Stop application writers with `docker compose down`.
2. Drop and recreate the target database.
3. Restore from the pre-restore database snapshot or the last known-good backup.
4. Run `alembic check`.
5. Restart the application and repeat the health and player-history verification checks.
6. Record the failure and rollback result in `docs/ops/restore-drill-log.md`.

## Drill Cadence

- Execute a staging restore drill at least monthly.
- Schedule the first drill after each schema-changing deployment within 7 days of deployment.
- If elapsed restore time exceeds 60 minutes, open an investigation and link it from the drill log.
