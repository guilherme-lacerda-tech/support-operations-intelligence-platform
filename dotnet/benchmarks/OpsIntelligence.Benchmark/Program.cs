using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Persistence;
using OpsIntelligence.Api.Services;

var arguments = CliArguments.Parse(args);
var events = ReadEvents(arguments.FixturePath, arguments.Count);
var runs = new List<EngineRunResult>();

for (var run = 0; run < arguments.Repetitions + arguments.Warmups; run++)
{
    var measured = run >= arguments.Warmups;
    var result = await RunOnceAsync(events, arguments, measured ? run - arguments.Warmups + 1 : 0);
    if (measured)
    {
        runs.Add(result);
    }
}

var output = new EngineBenchmarkResult("dotnet", arguments.Count, arguments.SqliteMode, runs);
Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions
{
    WriteIndented = false,
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase
}));

static async Task<EngineRunResult> RunOnceAsync(
    IReadOnlyList<SyntheticEventRequest> events,
    CliArguments arguments,
    int run)
{
    var dbPath = Path.Combine(arguments.DbRoot, $"dotnet-engine-{arguments.SqliteMode}-{arguments.Count}-{Guid.NewGuid():N}.sqlite3");
    var store = SqliteOpsStore.FromDataSource(
        dbPath,
        pooling: true,
        optimizeForLocalThroughput: arguments.SqliteMode == "wal");
    await store.InitializeAsync();

    var options = Options.Create(new OpsProcessingOptions
    {
        RetryDelayMilliseconds = 0,
        MaxActionAttempts = 3,
        WorkerEnabled = false
    });
    var queue = new ChannelActionSignalQueue();
    var processor = new ActionProcessor(store, new SyntheticActionExecutor(), options, TimeProvider.System);
    var ingestion = new EventIngestionService(store, new RuleEvaluator(), queue, options, TimeProvider.System);

    using var process = Process.GetCurrentProcess();
    process.Refresh();
    var cpuStart = process.TotalProcessorTime;
    var memoryStart = process.WorkingSet64;
    var errors = 0;
    var stopwatch = Stopwatch.StartNew();

    foreach (var operationEvent in events)
    {
        try
        {
            await ingestion.IngestAsync(operationEvent);
        }
        catch
        {
            errors++;
        }
    }

    for (var round = 0; round < 10; round++)
    {
        var batch = await processor.ProcessPendingAsync(10_000);
        if (batch.Processed == 0)
        {
            break;
        }
    }

    stopwatch.Stop();
    process.Refresh();
    var metrics = await store.GetMetricsAsync();
    TryDeleteSqliteFiles(dbPath);

    return new EngineRunResult(
        run,
        Math.Round(stopwatch.Elapsed.TotalMilliseconds, 2),
        Math.Round(events.Count / Math.Max(stopwatch.Elapsed.TotalSeconds, 0.001), 2),
        Math.Round((process.TotalProcessorTime - cpuStart).TotalMilliseconds, 2),
        Math.Round(memoryStart / 1024d / 1024d, 2),
        Math.Round(process.WorkingSet64 / 1024d / 1024d, 2),
        errors,
        metrics.Events,
        metrics.Incidents,
        metrics.Actions,
        metrics.CooldownSuppressions,
        metrics.SucceededActions,
        metrics.FailedActions,
        metrics.RetryAttempts,
        metrics.PermanentFailures);
}

static IReadOnlyList<SyntheticEventRequest> ReadEvents(string fixturePath, int count)
{
    var jsonOptions = new JsonSerializerOptions
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        PropertyNameCaseInsensitive = true
    };
    var events = new List<SyntheticEventRequest>(count);
    foreach (var line in File.ReadLines(fixturePath))
    {
        if (events.Count >= count)
        {
            break;
        }

        var shared = JsonSerializer.Deserialize<SharedEvent>(line, jsonOptions)!;
        events.Add(new SyntheticEventRequest
        {
            Source = shared.Source,
            AssetId = shared.AssetId,
            Category = shared.Category,
            Severity = shared.Severity,
            Message = shared.Message,
            ExecutorMode = shared.ExecutorMode,
            OccurredAt = DateTimeOffset.Parse(shared.OccurredAt)
        });
    }

    return events;
}

static void TryDeleteSqliteFiles(string dbPath)
{
    foreach (var path in new[] { dbPath, $"{dbPath}-wal", $"{dbPath}-shm" })
    {
        try
        {
            if (File.Exists(path))
            {
                File.Delete(path);
            }
        }
        catch
        {
        }
    }
}

internal sealed record SharedEvent(
    string AssetId,
    string Source,
    string Category,
    int Severity,
    string OccurredAt,
    string Message,
    string ExecutorMode);

internal sealed record EngineRunResult(
    int Run,
    double TotalMilliseconds,
    double EventsPerSecond,
    double CpuMilliseconds,
    double WorkingSetStartMb,
    double WorkingSetEndMb,
    int Errors,
    long Events,
    long Incidents,
    long Actions,
    long CooldownSuppressions,
    long SucceededActions,
    long FailedActions,
    long RetryAttempts,
    long PermanentFailures);

internal sealed record EngineBenchmarkResult(
    string Runtime,
    int Count,
    string SqliteMode,
    IReadOnlyList<EngineRunResult> Runs);

internal sealed class CliArguments
{
    public required string FixturePath { get; init; }
    public required string DbRoot { get; init; }
    public int Count { get; init; }
    public int Repetitions { get; init; }
    public int Warmups { get; init; }
    public string SqliteMode { get; init; } = "wal";

    public static CliArguments Parse(string[] args)
    {
        var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (var index = 0; index < args.Length; index += 2)
        {
            if (index + 1 >= args.Length || !args[index].StartsWith("--", StringComparison.Ordinal))
            {
                throw new ArgumentException("Arguments must use --name value pairs.");
            }

            values[args[index][2..]] = args[index + 1];
        }

        return new CliArguments
        {
            FixturePath = Require(values, "fixture"),
            DbRoot = values.GetValueOrDefault("db-root", Path.GetTempPath()),
            Count = int.Parse(values.GetValueOrDefault("count", "1000")),
            Repetitions = int.Parse(values.GetValueOrDefault("repetitions", "5")),
            Warmups = int.Parse(values.GetValueOrDefault("warmups", "1")),
            SqliteMode = values.GetValueOrDefault("sqlite-mode", "wal")
        };
    }

    private static string Require(Dictionary<string, string> values, string key) =>
        values.TryGetValue(key, out var value) && !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new ArgumentException($"Missing --{key}.");
}
