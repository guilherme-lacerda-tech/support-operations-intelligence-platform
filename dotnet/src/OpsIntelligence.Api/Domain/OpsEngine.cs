using Microsoft.Data.Sqlite;
using Microsoft.Extensions.Options;

namespace OpsIntelligence.Api.Domain;

public sealed class OpsEngine
{
    public const int WarningSeverity = 50;
    public const int CriticalSeverity = 80;

    private readonly OpsDatabase _database;
    private readonly OpsOptions _options;
    private readonly ILogger<OpsEngine> _logger;

    public OpsEngine(OpsDatabase database, IOptions<OpsOptions> options, ILogger<OpsEngine> logger)
    {
        _database = database;
        _options = options.Value;
        _logger = logger;
    }

    public ProcessResult Process(EventRequest request)
    {
        var occurredAt = (request.OccurredAt ?? DateTimeOffset.UtcNow).ToUniversalTime();
        var executorMode = NormalizeExecutorMode(request.ExecutorMode);
        using var connection = _database.OpenConnection();
        using var transaction = connection.BeginTransaction();

        var eventId = InsertEvent(connection, transaction, request, occurredAt, executorMode);
        InsertAudit(
            connection,
            transaction,
            "event_recorded",
            "event",
            eventId,
            EventAuditMessage(request.Severity),
            occurredAt);

        if (request.Severity < WarningSeverity)
        {
            transaction.Commit();
            _logger.LogInformation("Recorded normal event {EventId} for {AssetId}", eventId, request.AssetId);
            return new ProcessResult(eventId, null, null, "normal");
        }

        if (InCooldown(connection, transaction, request.AssetId, request.Category, occurredAt))
        {
            InsertAudit(
                connection,
                transaction,
                "event_suppressed",
                "event",
                eventId,
                "Cooldown suppressed duplicate incident/action for same asset and category",
                occurredAt);
            transaction.Commit();
            return new ProcessResult(eventId, null, null, "cooldown");
        }

        var incidentId = InsertIncident(connection, transaction, request, eventId, occurredAt);
        InsertAudit(
            connection,
            transaction,
            "incident_created",
            "incident",
            incidentId,
            IncidentSummary(request),
            occurredAt);

        if (request.Severity < CriticalSeverity)
        {
            transaction.Commit();
            return new ProcessResult(eventId, incidentId, null, "warning_no_action");
        }

        var actionId = InsertAction(connection, transaction, incidentId, occurredAt, executorMode);
        InsertAudit(
            connection,
            transaction,
            "action_queued",
            "action",
            actionId,
            "Critical event queued follow-up action",
            occurredAt);
        transaction.Commit();
        return new ProcessResult(eventId, incidentId, actionId, null);
    }

    private long InsertEvent(
        SqliteConnection connection,
        SqliteTransaction transaction,
        EventRequest request,
        DateTimeOffset occurredAt,
        string executorMode)
    {
        OpsDatabase.ExecuteNonQuery(
            connection,
            transaction,
            """
            INSERT INTO events(asset_id, source, category, severity, occurred_at, message, executor_mode, created_at)
            VALUES(@asset_id, @source, @category, @severity, @occurred_at, @message, @executor_mode, @created_at);
            """,
            ("@asset_id", request.AssetId),
            ("@source", request.Source),
            ("@category", request.Category),
            ("@severity", request.Severity),
            ("@occurred_at", OpsDatabase.FormatDate(occurredAt)),
            ("@message", request.Message),
            ("@executor_mode", executorMode),
            ("@created_at", OpsDatabase.FormatDate(DateTimeOffset.UtcNow)));
        return OpsDatabase.ExecuteScalarLong(connection, transaction, "SELECT last_insert_rowid();");
    }

    private long InsertIncident(
        SqliteConnection connection,
        SqliteTransaction transaction,
        EventRequest request,
        long eventId,
        DateTimeOffset occurredAt)
    {
        var summary = IncidentSummary(request);
        OpsDatabase.ExecuteNonQuery(
            connection,
            transaction,
            """
            INSERT INTO incidents(asset_id, event_id, category, state, summary, created_at, updated_at)
            VALUES(@asset_id, @event_id, @category, 'open', @summary, @created_at, @updated_at);
            """,
            ("@asset_id", request.AssetId),
            ("@event_id", eventId),
            ("@category", request.Category),
            ("@summary", summary),
            ("@created_at", OpsDatabase.FormatDate(occurredAt)),
            ("@updated_at", OpsDatabase.FormatDate(occurredAt)));
        return OpsDatabase.ExecuteScalarLong(connection, transaction, "SELECT last_insert_rowid();");
    }

    private static long InsertAction(
        SqliteConnection connection,
        SqliteTransaction transaction,
        long incidentId,
        DateTimeOffset occurredAt,
        string executorMode)
    {
        OpsDatabase.ExecuteNonQuery(
            connection,
            transaction,
            """
            INSERT INTO actions(incident_id, action_type, state, attempts, detail, created_at, updated_at)
            VALUES(@incident_id, 'create_ticket', 'queued', 0, @detail, @created_at, @updated_at);
            """,
            ("@incident_id", incidentId),
            ("@detail", $"executor_mode={executorMode}"),
            ("@created_at", OpsDatabase.FormatDate(occurredAt)),
            ("@updated_at", OpsDatabase.FormatDate(occurredAt)));
        return OpsDatabase.ExecuteScalarLong(connection, transaction, "SELECT last_insert_rowid();");
    }

    public static void InsertAudit(
        SqliteConnection connection,
        SqliteTransaction transaction,
        string eventType,
        string entityType,
        long entityId,
        string message,
        DateTimeOffset createdAt)
    {
        OpsDatabase.ExecuteNonQuery(
            connection,
            transaction,
            """
            INSERT INTO audit_logs(event_type, entity_type, entity_id, message, created_at)
            VALUES(@event_type, @entity_type, @entity_id, @message, @created_at);
            """,
            ("@event_type", eventType),
            ("@entity_type", entityType),
            ("@entity_id", entityId),
            ("@message", message),
            ("@created_at", OpsDatabase.FormatDate(createdAt)));
    }

    private bool InCooldown(
        SqliteConnection connection,
        SqliteTransaction transaction,
        string assetId,
        string category,
        DateTimeOffset occurredAt)
    {
        var threshold = occurredAt.AddMinutes(-_options.CooldownMinutes);
        var count = OpsDatabase.ExecuteScalarLong(
            connection,
            transaction,
            """
            SELECT COUNT(*)
            FROM incidents
            WHERE asset_id = @asset_id
              AND category = @category
              AND state <> 'resolved'
              AND created_at >= @threshold;
            """,
            ("@asset_id", assetId),
            ("@category", category),
            ("@threshold", OpsDatabase.FormatDate(threshold)));
        return count > 0;
    }

    private static string EventAuditMessage(int severity)
    {
        if (severity < WarningSeverity)
        {
            return "Normal event persisted without incident/action";
        }

        return severity < CriticalSeverity
            ? "Warning event persisted for incident review"
            : "Critical event persisted for incident/action evaluation";
    }

    private static string IncidentSummary(EventRequest request)
    {
        var level = request.Severity >= CriticalSeverity ? "critical" : "warning";
        return $"Synthetic severity policy: {request.AssetId} reported {level} {request.Category}";
    }

    private static string NormalizeExecutorMode(string value) =>
        value switch
        {
            "transient_failure" => value,
            "permanent_failure" => value,
            _ => "success",
        };
}
