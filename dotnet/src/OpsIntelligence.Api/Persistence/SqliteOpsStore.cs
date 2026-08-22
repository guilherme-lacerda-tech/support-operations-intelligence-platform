using System.Globalization;
using Microsoft.Data.Sqlite;
using OpsIntelligence.Api.Domain;

namespace OpsIntelligence.Api.Persistence;

public sealed class SqliteOpsStore
{
    private readonly string _connectionString;
    private readonly bool _optimizeForLocalThroughput;

    public SqliteOpsStore(string connectionString, bool optimizeForLocalThroughput = true)
    {
        _connectionString = connectionString;
        _optimizeForLocalThroughput = optimizeForLocalThroughput;
    }

    public static SqliteOpsStore FromDataSource(
        string dataSource,
        bool pooling = true,
        bool optimizeForLocalThroughput = true)
    {
        var fullPath = Path.GetFullPath(dataSource);
        var directory = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrWhiteSpace(directory))
        {
            Directory.CreateDirectory(directory);
        }

        var builder = new SqliteConnectionStringBuilder
        {
            DataSource = fullPath,
            Mode = SqliteOpenMode.ReadWriteCreate,
            Pooling = pooling
        };

        return new SqliteOpsStore(builder.ToString(), optimizeForLocalThroughput);
    }

    public async Task InitializeAsync(CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await ExecuteAsync(connection, """
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                category TEXT NOT NULL,
                severity INTEGER NOT NULL,
                message TEXT NOT NULL,
                executor_mode TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """, cancellationToken);
        await ExecuteAsync(connection, """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                category TEXT NOT NULL,
                severity INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """, cancellationToken);
        await ExecuteAsync(connection, """
            CREATE TABLE IF NOT EXISTS actions (
                id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                executor_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL,
                max_attempts INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT NULL
            );
            """, cancellationToken);
        await ExecuteAsync(connection, """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """, cancellationToken);
        await ExecuteAsync(connection, "CREATE INDEX IF NOT EXISTS ix_incidents_recent ON incidents(asset_id, category, status, created_at);", cancellationToken);
        await ExecuteAsync(connection, "CREATE INDEX IF NOT EXISTS ix_actions_due ON actions(status, next_attempt_at);", cancellationToken);
        await ExecuteAsync(connection, "CREATE INDEX IF NOT EXISTS ix_audit_type ON audit_logs(event_type, created_at);", cancellationToken);
    }

    public async Task<EventIngestionResult> RecordIngestionDecisionAsync(
        OperationEvent operationEvent,
        bool createIncident,
        bool queueAction,
        string actionType,
        int maxActionAttempts,
        TimeSpan cooldown,
        DateTimeOffset now,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);

        // BEGIN IMMEDIATE makes cooldown check + incident/action creation one SQLite write decision.
        await ExecuteAsync(connection, "BEGIN IMMEDIATE;", cancellationToken);
        try
        {
            await InsertEventAsync(connection, operationEvent, cancellationToken);
            await AddAuditAsync(connection, "event", operationEvent.Id, AuditEvents.EventReceived, "Synthetic event received.", now, cancellationToken);

            if (!createIncident)
            {
                await AddAuditAsync(connection, "event", operationEvent.Id, AuditEvents.NormalEventRecorded, "No incident rule matched.", now, cancellationToken);
                await ExecuteAsync(connection, "COMMIT;", cancellationToken);
                return new EventIngestionResult(operationEvent.Id, "ignored", null, null, false);
            }

            var recentIncident = await GetRecentOpenIncidentAsync(
                connection,
                operationEvent.AssetId,
                operationEvent.Category,
                now.Subtract(cooldown),
                cancellationToken);
            if (recentIncident is not null)
            {
                await AddAuditAsync(
                    connection,
                    "incident",
                    recentIncident.Id,
                    AuditEvents.CooldownSuppressed,
                    $"Duplicate event suppressed during {cooldown.TotalSeconds:N0}s cooldown.",
                    now,
                    cancellationToken);
                await ExecuteAsync(connection, "COMMIT;", cancellationToken);
                return new EventIngestionResult(operationEvent.Id, "cooldown_suppressed", recentIncident.Id, null, true);
            }

            var incident = new Incident(
                NewId("inc"),
                operationEvent.Id,
                operationEvent.AssetId,
                operationEvent.Category,
                operationEvent.Severity,
                IncidentStatuses.Open,
                now,
                now);
            await CreateIncidentAsync(connection, incident, cancellationToken);
            await AddAuditAsync(connection, "incident", incident.Id, AuditEvents.IncidentCreated, "Synthetic incident opened.", now, cancellationToken);

            if (!queueAction)
            {
                await ExecuteAsync(connection, "COMMIT;", cancellationToken);
                return new EventIngestionResult(operationEvent.Id, "incident_created", incident.Id, null, false);
            }

            var action = new QueuedAction(
                NewId("act"),
                incident.Id,
                operationEvent.AssetId,
                actionType,
                operationEvent.ExecutorMode,
                ActionStatuses.Queued,
                0,
                maxActionAttempts,
                now,
                now,
                now,
                null);
            await CreateActionAsync(connection, action, cancellationToken);
            await AddAuditAsync(connection, "action", action.Id, AuditEvents.ActionQueued, "Synthetic action queued.", now, cancellationToken);

            await ExecuteAsync(connection, "COMMIT;", cancellationToken);
            return new EventIngestionResult(operationEvent.Id, "action_queued", incident.Id, action.Id, false);
        }
        catch
        {
            await RollbackQuietlyAsync(connection);
            throw;
        }
    }

    public async Task InsertEventAsync(OperationEvent operationEvent, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await InsertEventAsync(connection, operationEvent, cancellationToken);
    }

    private static async Task InsertEventAsync(
        SqliteConnection connection,
        OperationEvent operationEvent,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO events (id, source, asset_id, category, severity, message, executor_mode, occurred_at, created_at)
            VALUES ($id, $source, $assetId, $category, $severity, $message, $executorMode, $occurredAt, $createdAt);
            """;
        Add(command, "$id", operationEvent.Id);
        Add(command, "$source", operationEvent.Source);
        Add(command, "$assetId", operationEvent.AssetId);
        Add(command, "$category", operationEvent.Category);
        Add(command, "$severity", operationEvent.Severity);
        Add(command, "$message", operationEvent.Message);
        Add(command, "$executorMode", operationEvent.ExecutorMode);
        Add(command, "$occurredAt", Format(operationEvent.OccurredAt));
        Add(command, "$createdAt", Format(operationEvent.CreatedAt));
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<Incident?> GetRecentOpenIncidentAsync(
        string assetId,
        string category,
        DateTimeOffset since,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        return await GetRecentOpenIncidentAsync(connection, assetId, category, since, cancellationToken);
    }

    private static async Task<Incident?> GetRecentOpenIncidentAsync(
        SqliteConnection connection,
        string assetId,
        string category,
        DateTimeOffset since,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, event_id, asset_id, category, severity, status, created_at, updated_at
            FROM incidents
            WHERE asset_id = $assetId
              AND category = $category
              AND status = $status
              AND created_at >= $since
            ORDER BY created_at DESC
            LIMIT 1;
            """;
        Add(command, "$assetId", assetId);
        Add(command, "$category", category);
        Add(command, "$status", IncidentStatuses.Open);
        Add(command, "$since", Format(since));

        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        return await reader.ReadAsync(cancellationToken) ? ReadIncident(reader) : null;
    }

    public async Task CreateIncidentAsync(Incident incident, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await CreateIncidentAsync(connection, incident, cancellationToken);
    }

    private static async Task CreateIncidentAsync(
        SqliteConnection connection,
        Incident incident,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO incidents (id, event_id, asset_id, category, severity, status, created_at, updated_at)
            VALUES ($id, $eventId, $assetId, $category, $severity, $status, $createdAt, $updatedAt);
            """;
        Add(command, "$id", incident.Id);
        Add(command, "$eventId", incident.EventId);
        Add(command, "$assetId", incident.AssetId);
        Add(command, "$category", incident.Category);
        Add(command, "$severity", incident.Severity);
        Add(command, "$status", incident.Status);
        Add(command, "$createdAt", Format(incident.CreatedAt));
        Add(command, "$updatedAt", Format(incident.UpdatedAt));
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task CreateActionAsync(QueuedAction action, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await CreateActionAsync(connection, action, cancellationToken);
    }

    private static async Task CreateActionAsync(
        SqliteConnection connection,
        QueuedAction action,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO actions (
                id, incident_id, asset_id, action_type, executor_mode, status, attempts, max_attempts,
                created_at, updated_at, next_attempt_at, last_error)
            VALUES (
                $id, $incidentId, $assetId, $actionType, $executorMode, $status, $attempts, $maxAttempts,
                $createdAt, $updatedAt, $nextAttemptAt, $lastError);
            """;
        AddActionParameters(command, action);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<QueuedAction>> GetDueActionsAsync(
        int limit,
        DateTimeOffset utcNow,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, incident_id, asset_id, action_type, executor_mode, status, attempts, max_attempts,
                   created_at, updated_at, next_attempt_at, last_error
            FROM actions
            WHERE status IN ($queued, $retry)
              AND next_attempt_at <= $now
            ORDER BY next_attempt_at ASC, created_at ASC
            LIMIT $limit;
            """;
        Add(command, "$queued", ActionStatuses.Queued);
        Add(command, "$retry", ActionStatuses.Retry);
        Add(command, "$now", Format(utcNow));
        Add(command, "$limit", limit);

        var actions = new List<QueuedAction>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            actions.Add(ReadAction(reader));
        }

        return actions;
    }

    public async Task UpdateActionAsync(QueuedAction action, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            UPDATE actions
            SET status = $status,
                attempts = $attempts,
                updated_at = $updatedAt,
                next_attempt_at = $nextAttemptAt,
                last_error = $lastError
            WHERE id = $id;
            """;
        Add(command, "$id", action.Id);
        Add(command, "$status", action.Status);
        Add(command, "$attempts", action.Attempts);
        Add(command, "$updatedAt", Format(action.UpdatedAt));
        Add(command, "$nextAttemptAt", Format(action.NextAttemptAt));
        Add(command, "$lastError", action.LastError);
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task AddAuditAsync(
        string entityType,
        string entityId,
        string eventType,
        string message,
        DateTimeOffset createdAt,
        CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await AddAuditAsync(connection, entityType, entityId, eventType, message, createdAt, cancellationToken);
    }

    private static async Task AddAuditAsync(
        SqliteConnection connection,
        string entityType,
        string entityId,
        string eventType,
        string message,
        DateTimeOffset createdAt,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = """
            INSERT INTO audit_logs (id, entity_type, entity_id, event_type, message, created_at)
            VALUES ($id, $entityType, $entityId, $eventType, $message, $createdAt);
            """;
        Add(command, "$id", NewId("aud"));
        Add(command, "$entityType", entityType);
        Add(command, "$entityId", entityId);
        Add(command, "$eventType", eventType);
        Add(command, "$message", message);
        Add(command, "$createdAt", Format(createdAt));
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    public async Task<IReadOnlyList<Incident>> GetIncidentsAsync(int limit, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, event_id, asset_id, category, severity, status, created_at, updated_at
            FROM incidents
            ORDER BY created_at DESC
            LIMIT $limit;
            """;
        Add(command, "$limit", limit);

        var incidents = new List<Incident>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            incidents.Add(ReadIncident(reader));
        }

        return incidents;
    }

    public async Task<IReadOnlyList<QueuedAction>> GetActionsAsync(int limit, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, incident_id, asset_id, action_type, executor_mode, status, attempts, max_attempts,
                   created_at, updated_at, next_attempt_at, last_error
            FROM actions
            ORDER BY created_at DESC
            LIMIT $limit;
            """;
        Add(command, "$limit", limit);

        var actions = new List<QueuedAction>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            actions.Add(ReadAction(reader));
        }

        return actions;
    }

    public async Task<IReadOnlyList<AuditLogEntry>> GetAuditLogsAsync(int limit, CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await using var command = connection.CreateCommand();
        command.CommandText = """
            SELECT id, entity_type, entity_id, event_type, message, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT $limit;
            """;
        Add(command, "$limit", limit);

        var entries = new List<AuditLogEntry>();
        await using var reader = await command.ExecuteReaderAsync(cancellationToken);
        while (await reader.ReadAsync(cancellationToken))
        {
            entries.Add(ReadAudit(reader));
        }

        return entries;
    }

    public async Task<MetricsSnapshot> GetMetricsAsync(CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        return new MetricsSnapshot(
            await CountAsync(connection, "events", null, cancellationToken),
            await CountAsync(connection, "incidents", null, cancellationToken),
            await CountAsync(connection, "actions", null, cancellationToken),
            await CountAsync(connection, "actions", "status = 'queued'", cancellationToken),
            await CountAsync(connection, "actions", "status = 'succeeded'", cancellationToken),
            await CountAsync(connection, "actions", "status = 'retry'", cancellationToken),
            await CountAsync(connection, "actions", "status IN ('failed_permanent', 'failed_exhausted')", cancellationToken),
            await ScalarLongAsync(connection, "SELECT COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END), 0) FROM actions;", cancellationToken),
            await CountAsync(connection, "actions", "status = 'failed_permanent'", cancellationToken),
            await CountAsync(connection, "audit_logs", "event_type = 'COOLDOWN_SUPPRESSED'", cancellationToken),
            await CountAsync(connection, "audit_logs", null, cancellationToken));
    }

    public async Task ResetAsync(CancellationToken cancellationToken = default)
    {
        await using var connection = await OpenConnectionAsync(cancellationToken);
        await ExecuteAsync(connection, "DELETE FROM audit_logs;", cancellationToken);
        await ExecuteAsync(connection, "DELETE FROM actions;", cancellationToken);
        await ExecuteAsync(connection, "DELETE FROM incidents;", cancellationToken);
        await ExecuteAsync(connection, "DELETE FROM events;", cancellationToken);
    }

    public static string NewId(string prefix) => $"{prefix}_{Guid.NewGuid():N}";

    private async Task<SqliteConnection> OpenConnectionAsync(CancellationToken cancellationToken)
    {
        var connection = new SqliteConnection(_connectionString);
        await connection.OpenAsync(cancellationToken);
        await ExecuteAsync(connection, "PRAGMA busy_timeout=30000;", cancellationToken);
        if (_optimizeForLocalThroughput)
        {
            await using var command = connection.CreateCommand();
            command.CommandText = "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA temp_store=MEMORY;";
            await command.ExecuteNonQueryAsync(cancellationToken);
        }

        return connection;
    }

    private static async Task ExecuteAsync(SqliteConnection connection, string sql, CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        await command.ExecuteNonQueryAsync(cancellationToken);
    }

    private static async Task RollbackQuietlyAsync(SqliteConnection connection)
    {
        try
        {
            await ExecuteAsync(connection, "ROLLBACK;", CancellationToken.None);
        }
        catch (SqliteException)
        {
        }
        catch (InvalidOperationException)
        {
        }
    }

    private static async Task<long> CountAsync(
        SqliteConnection connection,
        string table,
        string? whereClause,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = whereClause is null
            ? $"SELECT COUNT(*) FROM {table};"
            : $"SELECT COUNT(*) FROM {table} WHERE {whereClause};";
        var value = await command.ExecuteScalarAsync(cancellationToken);
        return Convert.ToInt64(value, CultureInfo.InvariantCulture);
    }

    private static async Task<long> ScalarLongAsync(
        SqliteConnection connection,
        string sql,
        CancellationToken cancellationToken)
    {
        await using var command = connection.CreateCommand();
        command.CommandText = sql;
        var value = await command.ExecuteScalarAsync(cancellationToken);
        return Convert.ToInt64(value, CultureInfo.InvariantCulture);
    }

    private static void AddActionParameters(SqliteCommand command, QueuedAction action)
    {
        Add(command, "$id", action.Id);
        Add(command, "$incidentId", action.IncidentId);
        Add(command, "$assetId", action.AssetId);
        Add(command, "$actionType", action.ActionType);
        Add(command, "$executorMode", action.ExecutorMode);
        Add(command, "$status", action.Status);
        Add(command, "$attempts", action.Attempts);
        Add(command, "$maxAttempts", action.MaxAttempts);
        Add(command, "$createdAt", Format(action.CreatedAt));
        Add(command, "$updatedAt", Format(action.UpdatedAt));
        Add(command, "$nextAttemptAt", Format(action.NextAttemptAt));
        Add(command, "$lastError", action.LastError);
    }

    private static void Add(SqliteCommand command, string name, object? value)
    {
        command.Parameters.AddWithValue(name, value ?? DBNull.Value);
    }

    private static Incident ReadIncident(SqliteDataReader reader) => new(
        reader.GetString(0),
        reader.GetString(1),
        reader.GetString(2),
        reader.GetString(3),
        reader.GetInt32(4),
        reader.GetString(5),
        Parse(reader.GetString(6)),
        Parse(reader.GetString(7)));

    private static QueuedAction ReadAction(SqliteDataReader reader) => new(
        reader.GetString(0),
        reader.GetString(1),
        reader.GetString(2),
        reader.GetString(3),
        reader.GetString(4),
        reader.GetString(5),
        reader.GetInt32(6),
        reader.GetInt32(7),
        Parse(reader.GetString(8)),
        Parse(reader.GetString(9)),
        Parse(reader.GetString(10)),
        reader.IsDBNull(11) ? null : reader.GetString(11));

    private static AuditLogEntry ReadAudit(SqliteDataReader reader) => new(
        reader.GetString(0),
        reader.GetString(1),
        reader.GetString(2),
        reader.GetString(3),
        reader.GetString(4),
        Parse(reader.GetString(5)));

    private static string Format(DateTimeOffset value) => value.ToUniversalTime().ToString("O", CultureInfo.InvariantCulture);

    private static DateTimeOffset Parse(string value) =>
        DateTimeOffset.Parse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
}
