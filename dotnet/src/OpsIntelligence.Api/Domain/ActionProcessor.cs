using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Options;

namespace OpsIntelligence.Api.Domain;

public sealed class ActionProcessor
{
    private readonly OpsDatabase _database;
    private readonly OpsOptions _options;
    private readonly ILogger<ActionProcessor> _logger;

    public ActionProcessor(OpsDatabase database, IOptions<OpsOptions> options, ILogger<ActionProcessor> logger)
    {
        _database = database;
        _options = options.Value;
        _logger = logger;
    }

    public MaintenanceResult ProcessQueuedActions()
    {
        using var connection = _database.OpenConnection();
        var actionIds = GetQueuedActionIds(connection);
        var succeeded = 0;
        var failed = 0;

        foreach (var actionId in actionIds)
        {
            var state = ProcessAction(connection, actionId);
            if (state == "succeeded")
            {
                succeeded++;
            }
            else
            {
                failed++;
            }
        }

        return new MaintenanceResult(actionIds.Count, succeeded, failed);
    }

    public string ProcessAction(SqliteConnection connection, long actionId)
    {
        using var transaction = connection.BeginTransaction();
        var action = LoadAction(connection, transaction, actionId);
        var finalState = "failed";
        var finalDetail = "";

        for (var attempt = 1; attempt <= _options.MaxActionAttempts; attempt++)
        {
            if (ShouldSucceed(action.Detail, attempt))
            {
                finalState = "succeeded";
                finalDetail = $"synthetic {action.ActionType} completed";
                UpdateAction(connection, transaction, actionId, finalState, attempt, finalDetail);
                break;
            }

            finalDetail = FailureDetail(action.Detail);
            UpdateAction(connection, transaction, actionId, finalState, attempt, finalDetail);
        }

        var auditType = finalState == "succeeded" ? "action_succeeded" : "action_failed_final";
        OpsEngine.InsertAudit(
            connection,
            transaction,
            auditType,
            "action",
            actionId,
            $"{action.ActionType} finished as {finalState} after {GetAttempts(connection, transaction, actionId)} attempts",
            DateTimeOffset.UtcNow);
        transaction.Commit();
        _logger.LogInformation("Processed action {ActionId} as {State}", actionId, finalState);
        return finalState;
    }

    private static IReadOnlyList<long> GetQueuedActionIds(SqliteConnection connection)
    {
        using var command = OpsDatabase.CreateCommand(
            connection,
            null,
            "SELECT id FROM actions WHERE state = 'queued' ORDER BY created_at, id;");
        using var reader = command.ExecuteReader();
        var ids = new List<long>();
        while (reader.Read())
        {
            ids.Add(reader.GetInt64(0));
        }

        return ids;
    }

    private static ActionRecord LoadAction(SqliteConnection connection, SqliteTransaction transaction, long actionId)
    {
        using var command = OpsDatabase.CreateCommand(
            connection,
            transaction,
            "SELECT id, incident_id, action_type, state, attempts, detail, created_at FROM actions WHERE id = @id;",
            ("@id", actionId));
        using var reader = command.ExecuteReader();
        if (!reader.Read())
        {
            throw new InvalidOperationException($"Action {actionId} was not found.");
        }

        return new ActionRecord(
            reader.GetInt64(0),
            reader.GetInt64(1),
            reader.GetString(2),
            reader.GetString(3),
            reader.GetInt32(4),
            reader.GetString(5),
            OpsDatabase.ParseDate(reader.GetString(6)));
    }

    private static void UpdateAction(
        SqliteConnection connection,
        SqliteTransaction transaction,
        long actionId,
        string state,
        int attempts,
        string detail)
    {
        OpsDatabase.ExecuteNonQuery(
            connection,
            transaction,
            """
            UPDATE actions
            SET state = @state,
                attempts = @attempts,
                detail = @detail,
                updated_at = @updated_at
            WHERE id = @id;
            """,
            ("@state", state),
            ("@attempts", attempts),
            ("@detail", detail),
            ("@updated_at", OpsDatabase.FormatDate(DateTimeOffset.UtcNow)),
            ("@id", actionId));
    }

    private static int GetAttempts(SqliteConnection connection, SqliteTransaction transaction, long actionId) =>
        (int)OpsDatabase.ExecuteScalarLong(
            connection,
            transaction,
            "SELECT attempts FROM actions WHERE id = @id;",
            ("@id", actionId));

    private static bool ShouldSucceed(string detail, int attempt)
    {
        if (detail.Contains("permanent_failure", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        if (detail.Contains("transient_failure", StringComparison.OrdinalIgnoreCase))
        {
            return attempt >= 2;
        }

        return true;
    }

    private static string FailureDetail(string detail) =>
        detail.Contains("permanent_failure", StringComparison.OrdinalIgnoreCase)
            ? "synthetic permanent failure"
            : "synthetic transient failure";
}
