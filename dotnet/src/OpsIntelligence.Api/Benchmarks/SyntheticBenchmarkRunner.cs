using System.Diagnostics;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Services;

namespace OpsIntelligence.Api.Benchmarks;

public sealed class SyntheticBenchmarkRunner
{
    private readonly EventIngestionService _ingestion;
    private readonly ActionProcessor _processor;

    public SyntheticBenchmarkRunner(
        EventIngestionService ingestion,
        ActionProcessor processor)
    {
        _ingestion = ingestion;
        _processor = processor;
    }

    public async Task<BenchmarkResult> RunAsync(int count, CancellationToken cancellationToken = default)
    {
        var runId = Guid.NewGuid().ToString("N")[..8];
        using var process = Process.GetCurrentProcess();
        var cpuStart = process.TotalProcessorTime;
        var memoryStart = process.WorkingSet64;
        var stopwatch = Stopwatch.StartNew();
        var accepted = 0;
        var errors = 0;
        long incidentsCreated = 0;
        long actionsCreated = 0;
        long cooldownSuppressions = 0;

        for (var index = 0; index < count; index++)
        {
            try
            {
                var result = await _ingestion.IngestAsync(SyntheticFixtureFactory.Create(index, runId), cancellationToken);
                accepted++;
                incidentsCreated += result.IncidentId is not null && !result.Suppressed ? 1 : 0;
                actionsCreated += result.ActionId is not null ? 1 : 0;
                cooldownSuppressions += result.Suppressed ? 1 : 0;
            }
            catch
            {
                errors++;
            }
        }

        for (var round = 0; round < 20; round++)
        {
            var batch = await _processor.ProcessPendingAsync(1_000, cancellationToken);
            if (batch.Processed == 0)
            {
                break;
            }

            if (batch.Retried > 0)
            {
                await Task.Delay(125, cancellationToken);
            }
        }

        stopwatch.Stop();
        process.Refresh();
        var elapsedMs = Math.Max(1, stopwatch.Elapsed.TotalMilliseconds);

        return new BenchmarkResult(
            count,
            accepted,
            errors,
            incidentsCreated,
            actionsCreated,
            cooldownSuppressions,
            Math.Round(stopwatch.Elapsed.TotalMilliseconds, 2),
            Math.Round(accepted / (elapsedMs / 1_000), 2),
            Math.Round((process.TotalProcessorTime - cpuStart).TotalMilliseconds, 2),
            Math.Round(memoryStart / 1024d / 1024d, 2),
            Math.Round(process.WorkingSet64 / 1024d / 1024d, 2),
            "Synthetic local benchmark. Results include SQLite persistence and in-process rule evaluation/action processing.");
    }
}
