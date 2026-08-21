using System.Globalization;
using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Options;

namespace OpsIntelligence.Api.Domain;

public sealed class OpsDatabase
{
    private readonly OpsOptions _options;

    public OpsDatabase(IOptions<OpsOptions> options)
    {
        _options = options.Value;
        Initialize();
    }

    public SqliteConnection OpenConnection()
    {
        var connection = new SqliteConnection(_options.ConnectionString);
        connection.Open();
        return connection;
    }

    public void Initialize()
    {
        if (!string.Equals(_options.DatabasePath, ":memory:", StringComparison.OrdinalIgnoreCase))
        {
            var directory = Path.GetDirectoryName(Path.GetFullPath(_options.DatabasePath));
            if (!string.IsNullOrWhiteSpace(directory))
            {
                Directory.CreateDirectory(directory);
            }
        }

        using var connection = OpenConnection();
        if (_options.UseWal)
        {
            ExecuteNonQuery(connection, null, "PRAGMA journal_mode=WAL;");
            ExecuteNonQuery(connection, null, "PRAGMA synchronous=NORMAL;");
        }

        ExecuteNonQuery(
            connection,
            null,
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL,
                source TEXT NOT NULL,
                category TEXT NOT NULL,
                severity INTEGER NOT NULL,
                occurred_at TEXT NOT NULL,
                message TEXT NOT NULL,
                executor_mode TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """);
        ExecuteNonQuery(
            connection,
            null,
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT NOT NULL,
                event_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                state TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(event_id) REFERENCES events(id)
            );
            """);
        ExecuteNonQuery(
            connection,
            null,
            """
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(incident_id) REFERENCES incidents(id)
            );
            """);
        ExecuteNonQuery(
            connection,
            null,
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """);
        ExecuteNonQuery(connection, null, "CREATE INDEX IF NOT EXISTS ix_events_asset_category_occurred ON events(asset_id, category, occurred_at);");
        ExecuteNonQuery(connection, null, "CREATE INDEX IF NOT EXISTS ix_incidents_asset_category_created ON incidents(asset_id, category, created_at);");
        ExecuteNonQuery(connection, null, "CREATE INDEX IF NOT EXISTS ix_actions_state_created ON actions(state, created_at);");
        ExecuteNonQuery(connection, null, "CREATE INDEX IF NOT EXISTS ix_audit_event_type_created ON audit_logs(event_type, created_at);");
    }

    public IReadOnlyList<IncidentRecord> ListIncidents()
    {
        using var connection = OpenConnection();
        using var command = CreateCommand(
            connection,
            null,
            "SELECT id, asset_id, event_id, category, state, summary, created_at FROM incidents ORDER BY created_at DESC;");
        using var reader = command.ExecuteReader();
        var rows = new List<IncidentRecord>();
        while (reader.Read())
        {
            rows.Add(
                new IncidentRecord(
                    reader.GetInt64(0),
                    reader.GetString(1),
                    reader.GetInt64(2),
                    reader.GetString(3),
                    reader.GetString(4),
                    reader.GetString(5),
                    ParseDate(reader.GetString(6))));
        }

        return rows;
    }

    public IReadOnlyList<ActionRecord> ListActions()
    {
        using var connection = OpenConnection();
        using var command = CreateCommand(
            connection,
            null,
            "SELECT id, incident_id, action_type, state, attempts, detail, created_at FROM actions ORDER BY created_at DESC;");
        using var reader = command.ExecuteReader();
        var rows = new List<ActionRecord>();
        while (reader.Read())
        {
            rows.Add(
                new ActionRecord(
                    reader.GetInt64(0),
                    reader.GetInt64(1),
                    reader.GetString(2),
                    reader.GetString(3),
                    reader.GetInt32(4),
                    reader.GetString(5),
                    ParseDate(reader.GetString(6))));
        }

        return rows;
    }

    public IReadOnlyList<AuditRecord> ListAudit()
    {
        using var connection = OpenConnection();
        using var command = CreateCommand(
            connection,
            null,
            "SELECT id, event_type, entity_type, entity_id, message, created_at FROM audit_logs ORDER BY created_at DESC;");
        using var reader = command.ExecuteReader();
        var rows = new List<AuditRecord>();
        while (reader.Read())
        {
            rows.Add(
                new AuditRecord(
                    reader.GetInt64(0),
                    reader.GetString(1),
                    reader.GetString(2),
                    reader.GetInt64(3),
                    reader.GetString(4),
                    ParseDate(reader.GetString(5))));
        }

        return rows;
    }

    public MetricsSnapshot GetMetrics()
    {
        using var connection = OpenConnection();
        return new MetricsSnapshot(
            Count(connection, "events"),
            Count(connection, "incidents"),
            Count(connection, "actions"),
            Count(connection, "audit_logs"),
            CountWhere(connection, "audit_logs", "event_type = 'event_suppressed'"),
            CountWhere(connection, "actions", "state = 'queued'"),
            CountWhere(connection, "actions", "state = 'succeeded'"),
            CountWhere(connection, "actions", "state = 'failed'"),
            SumRetries(connection));
    }

    public IReadOnlyDictionary<string, int> Reset()
    {
        using var connection = OpenConnection();
        using var transaction = connection.BeginTransaction();
        var deleted = new Dictionary<string, int>
        {
            ["actions"] = ExecuteNonQuery(connection, transaction, "DELETE FROM actions;"),
            ["incidents"] = ExecuteNonQuery(connection, transaction, "DELETE FROM incidents;"),
            ["events"] = ExecuteNonQuery(connection, transaction, "DELETE FROM events;"),
            ["audit_logs"] = ExecuteNonQuery(connection, transaction, "DELETE FROM audit_logs;"),
        };
        transaction.Commit();
        return deleted;
    }

    public static string FormatDate(DateTimeOffset value) => value.UtcDateTime.ToString("O", CultureInfo.InvariantCulture);

    public static DateTimeOffset ParseDate(string value) =>
        DateTimeOffset.Parse(value, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);

    public static SqliteCommand CreateCommand(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        string commandText,
        params (string Name, object? Value)[] parameters)
    {
        var command = connection.CreateCommand();
        command.CommandText = commandText;
        command.Transaction = transaction;
        foreach (var (name, value) in parameters)
        {
            command.Parameters.AddWithValue(name, value ?? DBNull.Value);
        }

        return command;
    }

    public static int ExecuteNonQuery(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        string commandText,
        params (string Name, object? Value)[] parameters)
    {
        using var command = CreateCommand(connection, transaction, commandText, parameters);
        return command.ExecuteNonQuery();
    }

    public static long ExecuteScalarLong(
        SqliteConnection connection,
        SqliteTransaction? transaction,
        string commandText,
        params (string Name, object? Value)[] parameters)
    {
        using var command = CreateCommand(connection, transaction, commandText, parameters);
        return Convert.ToInt64(command.ExecuteScalar(), CultureInfo.InvariantCulture);
    }

    private static int Count(SqliteConnection connection, string table) =>
        (int)ExecuteScalarLong(connection, null, $"SELECT COUNT(*) FROM {table};");

    private static int CountWhere(SqliteConnection connection, string table, string predicate) =>
        (int)ExecuteScalarLong(connection, null, $"SELECT COUNT(*) FROM {table} WHERE {predicate};");

    private static int SumRetries(SqliteConnection connection) =>
        (int)ExecuteScalarLong(
            connection,
            null,
            "SELECT COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END), 0) FROM actions;");
}
