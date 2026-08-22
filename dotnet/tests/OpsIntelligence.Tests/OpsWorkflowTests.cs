using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Benchmarks;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Persistence;
using OpsIntelligence.Api.Services;

namespace OpsIntelligence.Tests;

public sealed class OpsWorkflowTests
{
    [Fact]
    public async Task CriticalEventCreatesIncidentAndAction()
    {
        using var harness = await Harness.CreateAsync();

        var result = await harness.Ingestion.IngestAsync(CriticalEvent());
        var metrics = await harness.Store.GetMetricsAsync();

        Assert.Equal("action_queued", result.Decision);
        Assert.NotNull(result.IncidentId);
        Assert.NotNull(result.ActionId);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
    }

    [Fact]
    public async Task CooldownSuppressesDuplicateIncidentAndAction()
    {
        using var harness = await Harness.CreateAsync();
        var first = CriticalEvent(assetId: "asset-cooldown");
        var second = CriticalEvent(assetId: "asset-cooldown");

        await harness.Ingestion.IngestAsync(first);
        var result = await harness.Ingestion.IngestAsync(second);
        var metrics = await harness.Store.GetMetricsAsync();

        Assert.True(result.Suppressed);
        Assert.Equal("cooldown_suppressed", result.Decision);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
        Assert.Equal(1, metrics.CooldownSuppressions);
    }

    [Fact]
    public async Task ConcurrentDuplicateEventsAreCollapsedByTransactionalCooldown()
    {
        for (var run = 0; run < 5; run++)
        {
            using var harness = await Harness.CreateAsync(options => options.CooldownSeconds = 300);

            var results = await IngestConcurrentDuplicatesAsync(harness, 100, $"asset-concurrent-{run}");
            var metrics = await harness.Store.GetMetricsAsync();

            AssertDuplicateCollapse(results, metrics, 100);
        }
    }

    [Fact]
    public async Task ThousandConcurrentDuplicateEventsAreCollapsedByTransactionalCooldown()
    {
        using var harness = await Harness.CreateAsync(options => options.CooldownSeconds = 300);

        var results = await IngestConcurrentDuplicatesAsync(harness, 1_000, "asset-concurrent-1000");
        var metrics = await harness.Store.GetMetricsAsync();

        AssertDuplicateCollapse(results, metrics, 1_000);
    }

    [Fact]
    public async Task CooldownExpiryAllowsNewIncidentAndAction()
    {
        var clock = new ManualTimeProvider(new DateTimeOffset(2026, 01, 01, 12, 00, 00, TimeSpan.Zero));
        using var harness = await Harness.CreateAsync(options => options.CooldownSeconds = 300, clock);

        var first = await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-expiry"));
        var suppressed = await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-expiry"));
        clock.Advance(TimeSpan.FromSeconds(301));
        var afterCooldown = await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-expiry"));

        var metrics = await harness.Store.GetMetricsAsync();

        Assert.Equal("action_queued", first.Decision);
        Assert.Equal("cooldown_suppressed", suppressed.Decision);
        Assert.Equal("action_queued", afterCooldown.Decision);
        Assert.Equal(3, metrics.Events);
        Assert.Equal(2, metrics.Incidents);
        Assert.Equal(2, metrics.Actions);
        Assert.Equal(1, metrics.CooldownSuppressions);
    }

    [Fact]
    public async Task WarningEventCreatesIncidentWithoutAction()
    {
        using var harness = await Harness.CreateAsync();

        var result = await harness.Ingestion.IngestAsync(new SyntheticEventRequest
        {
            Source = "synthetic-test",
            AssetId = "asset-warning",
            Category = "degraded",
            Severity = 65,
            Message = "Synthetic degradation"
        });
        var metrics = await harness.Store.GetMetricsAsync();

        Assert.Equal("incident_created", result.Decision);
        Assert.NotNull(result.IncidentId);
        Assert.Null(result.ActionId);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(0, metrics.Actions);
    }

    [Fact]
    public async Task NormalEventOnlyWritesAudit()
    {
        using var harness = await Harness.CreateAsync();

        var result = await harness.Ingestion.IngestAsync(new SyntheticEventRequest
        {
            Source = "synthetic-test",
            AssetId = "asset-normal",
            Category = "heartbeat",
            Severity = 12,
            Message = "Synthetic heartbeat"
        });
        var metrics = await harness.Store.GetMetricsAsync();

        Assert.Equal("ignored", result.Decision);
        Assert.Equal(1, metrics.Events);
        Assert.Equal(0, metrics.Incidents);
        Assert.Equal(0, metrics.Actions);
        Assert.Equal(2, metrics.AuditEntries);
    }

    [Fact]
    public async Task SuccessfulActionIsMarkedSucceeded()
    {
        using var harness = await Harness.CreateAsync();
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-success"));

        var batch = await harness.Processor.ProcessPendingAsync(10);
        var action = (await harness.Store.GetActionsAsync(10)).Single();

        Assert.Equal(1, batch.Succeeded);
        Assert.Equal(ActionStatuses.Succeeded, action.Status);
        Assert.Equal(1, action.Attempts);
    }

    [Fact]
    public async Task TransientFailureRetriesSameActionIdThenSucceeds()
    {
        using var harness = await Harness.CreateAsync(options => options.RetryDelayMilliseconds = 0);
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-transient", executorMode: ExecutorModes.TransientThenSuccess));

        await harness.Processor.ProcessPendingAsync(10);
        var retryAction = (await harness.Store.GetActionsAsync(10)).Single();
        await harness.Processor.ProcessPendingAsync(10);
        var succeededAction = (await harness.Store.GetActionsAsync(10)).Single();

        Assert.Equal(retryAction.Id, succeededAction.Id);
        Assert.Equal(ActionStatuses.Retry, retryAction.Status);
        Assert.Equal(ActionStatuses.Succeeded, succeededAction.Status);
        Assert.Equal(2, succeededAction.Attempts);
    }

    [Fact]
    public async Task PermanentFailureIsNotRetried()
    {
        using var harness = await Harness.CreateAsync();
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-permanent", executorMode: ExecutorModes.PermanentFailure));

        var batch = await harness.Processor.ProcessPendingAsync(10);
        var action = (await harness.Store.GetActionsAsync(10)).Single();

        Assert.Equal(1, batch.Failed);
        Assert.Equal(ActionStatuses.FailedPermanent, action.Status);
        Assert.Equal(1, action.Attempts);
    }

    [Fact]
    public async Task AuditTrailRecordsEventIncidentAndAction()
    {
        using var harness = await Harness.CreateAsync();
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-audit"));
        await harness.Processor.ProcessPendingAsync(10);

        var auditTypes = (await harness.Store.GetAuditLogsAsync(20)).Select(entry => entry.EventType).ToArray();

        Assert.Contains(AuditEvents.EventReceived, auditTypes);
        Assert.Contains(AuditEvents.IncidentCreated, auditTypes);
        Assert.Contains(AuditEvents.ActionQueued, auditTypes);
        Assert.Contains(AuditEvents.ActionSucceeded, auditTypes);
    }

    [Fact]
    public async Task DataPersistsAfterReopeningStore()
    {
        using var harness = await Harness.CreateAsync();
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-persistence"));

        var reopened = SqliteOpsStore.FromDataSource(harness.DbPath, pooling: false, optimizeForLocalThroughput: false);
        await reopened.InitializeAsync();
        var metrics = await reopened.GetMetricsAsync();

        Assert.Equal(1, metrics.Events);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
    }

    [Fact]
    public async Task BackgroundWorkerProcessesPersistedAction()
    {
        using var harness = await Harness.CreateAsync(options => options.WorkerPollMilliseconds = 10);
        var worker = new ActionWorker(
            harness.Processor,
            harness.Queue,
            Options.Create(harness.Options));

        await worker.StartAsync(CancellationToken.None);
        await harness.Ingestion.IngestAsync(CriticalEvent(assetId: "asset-worker"));
        await EventuallyAsync(async () =>
        {
            var action = (await harness.Store.GetActionsAsync(10)).Single();
            return action.Status == ActionStatuses.Succeeded;
        });
        await worker.StopAsync(CancellationToken.None);

        var metrics = await harness.Store.GetMetricsAsync();
        Assert.Equal(1, metrics.SucceededActions);
    }

    [Fact]
    public async Task BenchmarkRunnerReportsThroughputAndNoErrors()
    {
        using var harness = await Harness.CreateAsync(options => options.RetryDelayMilliseconds = 0);
        var runner = new SyntheticBenchmarkRunner(harness.Ingestion, harness.Processor);

        var result = await runner.RunAsync(100);

        Assert.Equal(100, result.AcceptedEvents);
        Assert.Equal(0, result.ProcessingErrors);
        Assert.True(result.EventsPerSecond > 0, result.ToString());
        Assert.True(result.IncidentsCreated > 0, result.ToString());
    }

    private static SyntheticEventRequest CriticalEvent(
        string assetId = "asset-critical",
        string executorMode = ExecutorModes.Success) => new()
    {
        Source = "synthetic-test",
        AssetId = assetId,
        Category = "offline",
        Severity = 90,
        Message = "Synthetic offline event",
        ExecutorMode = executorMode
    };

    private static async Task<EventIngestionResult[]> IngestConcurrentDuplicatesAsync(
        Harness harness,
        int count,
        string assetId)
    {
        var start = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        var tasks = Enumerable.Range(0, count)
            .Select(_ => Task.Run(async () =>
            {
                await start.Task;
                return await harness.Ingestion.IngestAsync(CriticalEvent(assetId: assetId));
            }))
            .ToArray();

        start.SetResult(true);
        return await Task.WhenAll(tasks);
    }

    private static void AssertDuplicateCollapse(
        IReadOnlyCollection<EventIngestionResult> results,
        MetricsSnapshot metrics,
        int totalEvents)
    {
        Assert.Equal(totalEvents, results.Count);
        Assert.Equal(1, results.Count(result => result.Decision == "action_queued"));
        Assert.Equal(totalEvents - 1, results.Count(result => result.Decision == "cooldown_suppressed"));
        Assert.Equal(totalEvents, metrics.Events);
        Assert.Equal(1, metrics.Incidents);
        Assert.Equal(1, metrics.Actions);
        Assert.Equal(totalEvents - 1, metrics.CooldownSuppressions);
    }

    private static async Task EventuallyAsync(Func<Task<bool>> condition)
    {
        var deadline = DateTimeOffset.UtcNow.AddSeconds(5);
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (await condition())
            {
                return;
            }

            await Task.Delay(25);
        }

        Assert.Fail("Condition was not met before timeout.");
    }

    private sealed class Harness : IDisposable
    {
        private Harness(
            string dbPath,
            SqliteOpsStore store,
            ChannelActionSignalQueue queue,
            ActionProcessor processor,
            EventIngestionService ingestion,
            OpsProcessingOptions options)
        {
            DbPath = dbPath;
            Store = store;
            Queue = queue;
            Processor = processor;
            Ingestion = ingestion;
            Options = options;
        }

        public string DbPath { get; }
        public SqliteOpsStore Store { get; }
        public ChannelActionSignalQueue Queue { get; }
        public ActionProcessor Processor { get; }
        public EventIngestionService Ingestion { get; }
        public OpsProcessingOptions Options { get; }

        public static async Task<Harness> CreateAsync(
            Action<MutableOptions>? configure = null,
            TimeProvider? timeProvider = null)
        {
            var dbPath = Path.Combine(Path.GetTempPath(), $"ops-intelligence-{Guid.NewGuid():N}.sqlite3");
            var options = new MutableOptions();
            configure?.Invoke(options);

            var immutableOptions = options.ToProcessingOptions();
            var store = SqliteOpsStore.FromDataSource(dbPath, pooling: false, optimizeForLocalThroughput: false);
            await store.InitializeAsync();
            var queue = new ChannelActionSignalQueue();
            var evaluator = new RuleEvaluator();
            var executor = new SyntheticActionExecutor();
            var clock = timeProvider ?? TimeProvider.System;
            var processor = new ActionProcessor(store, executor, Microsoft.Extensions.Options.Options.Create(immutableOptions), clock);
            var ingestion = new EventIngestionService(store, evaluator, queue, Microsoft.Extensions.Options.Options.Create(immutableOptions), clock);

            return new Harness(dbPath, store, queue, processor, ingestion, immutableOptions);
        }

        public void Dispose()
        {
            if (File.Exists(DbPath))
            {
                File.Delete(DbPath);
            }
        }
    }

    public sealed class MutableOptions
    {
        public int CooldownSeconds { get; set; } = 300;
        public int RetryDelayMilliseconds { get; set; } = 0;
        public int MaxActionAttempts { get; set; } = 3;
        public int WorkerBatchSize { get; set; } = 100;
        public int WorkerPollMilliseconds { get; set; } = 25;

        public OpsProcessingOptions ToProcessingOptions() => new()
        {
            CooldownSeconds = CooldownSeconds,
            RetryDelayMilliseconds = RetryDelayMilliseconds,
            MaxActionAttempts = MaxActionAttempts,
            WorkerBatchSize = WorkerBatchSize,
            WorkerPollMilliseconds = WorkerPollMilliseconds
        };
    }

    private sealed class ManualTimeProvider : TimeProvider
    {
        private DateTimeOffset _utcNow;

        public ManualTimeProvider(DateTimeOffset utcNow)
        {
            _utcNow = utcNow;
        }

        public override DateTimeOffset GetUtcNow() => _utcNow;

        public void Advance(TimeSpan value)
        {
            _utcNow = _utcNow.Add(value);
        }
    }
}
