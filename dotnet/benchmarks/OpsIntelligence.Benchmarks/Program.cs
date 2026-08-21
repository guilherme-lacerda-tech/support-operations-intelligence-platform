using System.Diagnostics;
using System.Text.Json;
using Microsoft.Extensions.Logging.Abstractions;
using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;

var arguments = ParseArgs(args);
if (!arguments.TryGetValue("workload", out var workloadPath))
{
    Console.Error.WriteLine("Usage: dotnet run -- --workload <jsonl> [--db <sqlite>] [--wal true|false]");
    return 2;
}

var databasePath = arguments.TryGetValue("db", out var db)
    ? db
    : Path.Combine(Path.GetTempPath(), $"ops-dotnet-bench-{Guid.NewGuid():N}.sqlite3");
var options = new OpsOptions
{
    DatabasePath = databasePath,
    UseWal = arguments.TryGetValue("wal", out var wal) && bool.TryParse(wal, out var parsedWal) && parsedWal,
};
var database = new OpsDatabase(Options.Create(options));
database.Reset();
var engine = new OpsEngine(database, Options.Create(options), NullLogger<OpsEngine>.Instance);
var processor = new ActionProcessor(database, Options.Create(options), NullLogger<ActionProcessor>.Instance);
var jsonOptions = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
var events = File.ReadLines(workloadPath)
    .Where(line => !string.IsNullOrWhiteSpace(line))
    .Select(line => JsonSerializer.Deserialize<EventRequest>(line, jsonOptions)!)
    .ToList();

var process = Process.GetCurrentProcess();
var cpuStart = process.TotalProcessorTime;
var stopwatch = Stopwatch.StartNew();
var skippedCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
{
    ["normal"] = 0,
    ["warning_no_action"] = 0,
    ["cooldown"] = 0,
};
foreach (var item in events)
{
    var processResult = engine.Process(item);
    if (processResult.SkippedReason is not null && skippedCounts.ContainsKey(processResult.SkippedReason))
    {
        skippedCounts[processResult.SkippedReason]++;
    }
}

var maintenance = processor.ProcessQueuedActions();
stopwatch.Stop();
process.Refresh();
var cpuMs = (process.TotalProcessorTime - cpuStart).TotalMilliseconds;
var metrics = database.GetMetrics();
var result = new SortedDictionary<string, object?>
{
    ["stack"] = "dotnet",
    ["workload"] = Path.GetFileName(workloadPath),
    ["wal"] = options.UseWal,
    ["elapsed_ms"] = Math.Round(stopwatch.Elapsed.TotalMilliseconds, 3),
    ["events_per_second"] = Math.Round(events.Count / stopwatch.Elapsed.TotalSeconds, 2),
    ["cpu_ms"] = Math.Round(cpuMs, 3),
    ["working_set_mb"] = Math.Round(process.WorkingSet64 / 1024d / 1024d, 2),
    ["processed_actions"] = maintenance.Processed,
    ["events"] = metrics.Events,
    ["incidents"] = metrics.Incidents,
    ["actions"] = metrics.Actions,
    ["audit_logs"] = metrics.AuditLogs,
    ["normal_events"] = skippedCounts["normal"],
    ["warning_incidents"] = skippedCounts["warning_no_action"],
    ["suppressions"] = skippedCounts["cooldown"],
    ["action_succeeded"] = metrics.SucceededActions,
    ["action_failed"] = metrics.FailedActions,
    ["retries"] = metrics.Retries,
    ["errors"] = 0,
};

Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
return 0;

static Dictionary<string, string> ParseArgs(string[] args)
{
    var parsed = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    for (var index = 0; index < args.Length; index++)
    {
        var item = args[index];
        if (!item.StartsWith("--", StringComparison.Ordinal))
        {
            continue;
        }

        var key = item[2..];
        var value = index + 1 < args.Length && !args[index + 1].StartsWith("--", StringComparison.Ordinal)
            ? args[++index]
            : "true";
        parsed[key] = value;
    }

    return parsed;
}
