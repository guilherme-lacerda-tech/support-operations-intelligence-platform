using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;

namespace OpsIntelligence.Tests;

public sealed class OpsEngineTests
{
    [Fact]
    public void CriticalEventCreatesIncidentAndAction()
    {
        var app = CreateHarness();

        var result = app.Engine.Process(NewEvent(severity: 92));

        Assert.NotNull(result.IncidentId);
        Assert.NotNull(result.ActionId);
        Assert.Null(result.SkippedReason);
        Assert.Equal(1, app.Database.GetMetrics().Incidents);
        Assert.Equal(1, app.Database.GetMetrics().Actions);
    }

    [Fact]
    public void CooldownSuppressesDuplicateForSameAssetAndCategory()
    {
        var app = CreateHarness();
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");

        app.Engine.Process(NewEvent(assetId: "ASSET-1", category: "offline", severity: 95, occurredAt: at));
        var repeated = app.Engine.Process(NewEvent(assetId: "ASSET-1", category: "offline", severity: 95, occurredAt: at.AddMinutes(5)));

        Assert.Equal("cooldown", repeated.SkippedReason);
        var metrics = app.Database.GetMetrics();
        Assert.Equal(2, metrics.Events);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
        Assert.Equal(1, metrics.Suppressions);
    }

    [Fact]
    public void CooldownDoesNotSuppressDifferentCategory()
    {
        var app = CreateHarness();
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");

        app.Engine.Process(NewEvent(assetId: "ASSET-1", category: "offline", severity: 95, occurredAt: at));
        var second = app.Engine.Process(NewEvent(assetId: "ASSET-1", category: "battery_low", severity: 95, occurredAt: at.AddMinutes(5)));

        Assert.Null(second.SkippedReason);
        Assert.Equal(2, app.Database.GetMetrics().Incidents);
    }

    [Fact]
    public void WarningCreatesIncidentWithoutAction()
    {
        var app = CreateHarness();

        var result = app.Engine.Process(NewEvent(severity: 70));

        Assert.NotNull(result.IncidentId);
        Assert.Null(result.ActionId);
        Assert.Equal("warning_no_action", result.SkippedReason);
        Assert.Equal(1, app.Database.GetMetrics().Incidents);
        Assert.Equal(0, app.Database.GetMetrics().Actions);
    }

    [Fact]
    public void NormalEventPersistsWithoutIncidentOrAction()
    {
        var app = CreateHarness();

        var result = app.Engine.Process(NewEvent(severity: 25));

        Assert.Null(result.IncidentId);
        Assert.Null(result.ActionId);
        Assert.Equal("normal", result.SkippedReason);
        var metrics = app.Database.GetMetrics();
        Assert.Equal(1, metrics.Events);
        Assert.Equal(0, metrics.Incidents);
        Assert.Equal(0, metrics.Actions);
    }

    [Fact]
    public void SuccessfulActionCompletesInOneAttempt()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent(executorMode: "success"));

        var result = app.Actions.ProcessQueuedActions();

        var action = Assert.Single(app.Database.ListActions());
        Assert.Equal(1, result.Processed);
        Assert.Equal("succeeded", action.State);
        Assert.Equal(1, action.Attempts);
    }

    [Fact]
    public void TransientFailureKeepsSameActionIdAndSucceeds()
    {
        var app = CreateHarness();
        var process = app.Engine.Process(NewEvent(executorMode: "transient_failure"));

        app.Actions.ProcessQueuedActions();

        var action = Assert.Single(app.Database.ListActions());
        Assert.Equal(process.ActionId, action.Id);
        Assert.Equal("succeeded", action.State);
        Assert.Equal(2, action.Attempts);
    }

    [Fact]
    public void RetryAttemptsAreCounted()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent(executorMode: "transient_failure"));

        app.Actions.ProcessQueuedActions();

        Assert.Equal(1, app.Database.GetMetrics().Retries);
    }

    [Fact]
    public void PermanentFailureRecordsFinalFailureAudit()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent(executorMode: "permanent_failure"));

        app.Actions.ProcessQueuedActions();

        var action = Assert.Single(app.Database.ListActions());
        Assert.Equal("failed", action.State);
        Assert.Equal(3, action.Attempts);
        Assert.Contains(app.Database.ListAudit(), audit => audit.EventType == "action_failed_final");
    }

    [Fact]
    public void AuditTrailIncludesEventIncidentActionAndExecution()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent());

        app.Actions.ProcessQueuedActions();

        var eventTypes = app.Database.ListAudit().Select(row => row.EventType).ToHashSet();
        Assert.Contains("event_recorded", eventTypes);
        Assert.Contains("incident_created", eventTypes);
        Assert.Contains("action_queued", eventTypes);
        Assert.Contains("action_succeeded", eventTypes);
    }

    [Fact]
    public void PersistenceSurvivesDatabaseReopen()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent());

        var reopened = CreateHarness(app.Options.DatabasePath);

        var metrics = reopened.Database.GetMetrics();
        Assert.Equal(1, metrics.Events);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
    }

    [Fact]
    public async Task BackgroundServiceProcessesPersistedAction()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent(executorMode: "success"));
        var service = new QueuedActionBackgroundService(
            app.Actions,
            Options.Create(app.Options),
            NullLogger<QueuedActionBackgroundService>.Instance);

        var result = await service.ProcessOnceAsync();

        Assert.Equal(1, result.Processed);
        Assert.Equal("succeeded", Assert.Single(app.Database.ListActions()).State);
    }

    [Fact]
    public void ResetClearsOperationalTables()
    {
        var app = CreateHarness();
        app.Engine.Process(NewEvent());

        var deleted = app.Database.Reset();

        Assert.Equal(1, deleted["actions"]);
        Assert.Equal(0, app.Database.GetMetrics().Events);
        Assert.Empty(app.Database.ListIncidents());
        Assert.Empty(app.Database.ListAudit());
    }

    [Fact]
    public void MetricsStayCoherentAcrossEventTypes()
    {
        var app = CreateHarness();
        var at = DateTimeOffset.Parse("2026-01-01T00:00:00Z");
        app.Engine.Process(NewEvent(assetId: "A-1", severity: 20, occurredAt: at));
        app.Engine.Process(NewEvent(assetId: "A-2", severity: 70, occurredAt: at.AddMinutes(30)));
        app.Engine.Process(NewEvent(assetId: "A-3", severity: 90, occurredAt: at.AddMinutes(60), executorMode: "transient_failure"));

        app.Actions.ProcessQueuedActions();

        var metrics = app.Database.GetMetrics();
        Assert.Equal(3, metrics.Events);
        Assert.Equal(2, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
        Assert.Equal(1, metrics.SucceededActions);
        Assert.Equal(1, metrics.Retries);
        Assert.True(metrics.AuditLogs >= 6);
    }

    private static TestHarness CreateHarness(string? databasePath = null)
    {
        var options = new OpsOptions
        {
            DatabasePath = databasePath ?? Path.Combine(Path.GetTempPath(), $"ops-intel-{Guid.NewGuid():N}.sqlite3"),
            CooldownMinutes = 20,
            MaxActionAttempts = 3,
        };
        var database = new OpsDatabase(Options.Create(options));
        var engine = new OpsEngine(database, Options.Create(options), NullLogger<OpsEngine>.Instance);
        var actions = new ActionProcessor(database, Options.Create(options), NullLogger<ActionProcessor>.Instance);
        return new TestHarness(options, database, engine, actions);
    }

    private static EventRequest NewEvent(
        string assetId = "ASSET-1",
        string category = "offline",
        int severity = 90,
        DateTimeOffset? occurredAt = null,
        string executorMode = "success") =>
        new(
            assetId,
            "unit-test",
            category,
            severity,
            occurredAt ?? DateTimeOffset.Parse("2026-01-01T00:00:00Z"),
            "Synthetic event for clean-room tests",
            executorMode);

    private sealed record TestHarness(
        OpsOptions Options,
        OpsDatabase Database,
        OpsEngine Engine,
        ActionProcessor Actions);
}
