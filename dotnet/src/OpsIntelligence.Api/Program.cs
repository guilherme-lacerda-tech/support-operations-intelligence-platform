using OpsIntelligence.Api.Benchmarks;
using OpsIntelligence.Api.Domain;
using OpsIntelligence.Api.Persistence;
using OpsIntelligence.Api.Services;

var builder = WebApplication.CreateBuilder(args);

builder.Services.Configure<OpsProcessingOptions>(
    builder.Configuration.GetSection(OpsProcessingOptions.SectionName));
builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton(provider =>
{
    var configuration = provider.GetRequiredService<IConfiguration>();
    var configuredPath = configuration["OpsDb:Path"];
    var dataSource = string.IsNullOrWhiteSpace(configuredPath)
        ? Path.Combine(AppContext.BaseDirectory, "ops-intelligence-cleanroom.sqlite3")
        : configuredPath;
    var pooling = configuration.GetValue("OpsDb:Pooling", true);
    var optimizeForLocalThroughput = configuration.GetValue("OpsDb:OptimizeForLocalThroughput", true);

    return SqliteOpsStore.FromDataSource(dataSource, pooling, optimizeForLocalThroughput);
});
builder.Services.AddSingleton<IActionSignalQueue, ChannelActionSignalQueue>();
builder.Services.AddSingleton<RuleEvaluator>();
builder.Services.AddSingleton<SyntheticActionExecutor>();
builder.Services.AddSingleton<ActionProcessor>();
builder.Services.AddSingleton<EventIngestionService>();
builder.Services.AddSingleton<SyntheticBenchmarkRunner>();
if (builder.Configuration.GetValue("OpsProcessing:WorkerEnabled", true))
{
    builder.Services.AddHostedService<ActionWorker>();
}

var app = builder.Build();

await app.Services.GetRequiredService<SqliteOpsStore>().InitializeAsync();

app.MapGet("/", () => Results.Ok(new
{
    name = "Ops Intelligence Clean-Room .NET POC",
    mode = "synthetic-data-only",
    endpoints = new[] { "/events", "/metrics", "/incidents", "/actions", "/audit", "/benchmarks/run/{count}" }
}));

app.MapGet("/health", () => Results.Ok(new { status = "ok", utc = DateTimeOffset.UtcNow }));

app.MapPost("/events", async (
    SyntheticEventRequest request,
    EventIngestionService ingestion,
    CancellationToken cancellationToken) =>
{
    var result = await ingestion.IngestAsync(request, cancellationToken);
    return Results.Accepted($"/events/{result.EventId}", result);
});

app.MapGet("/metrics", async (SqliteOpsStore store, CancellationToken cancellationToken) =>
    Results.Ok(await store.GetMetricsAsync(cancellationToken)));

app.MapGet("/incidents", async (SqliteOpsStore store, CancellationToken cancellationToken) =>
    Results.Ok(await store.GetIncidentsAsync(100, cancellationToken)));

app.MapGet("/actions", async (SqliteOpsStore store, CancellationToken cancellationToken) =>
    Results.Ok(await store.GetActionsAsync(100, cancellationToken)));

app.MapGet("/audit", async (SqliteOpsStore store, CancellationToken cancellationToken) =>
    Results.Ok(await store.GetAuditLogsAsync(100, cancellationToken)));

app.MapPost("/maintenance/process-actions", async (
    ActionProcessor processor,
    CancellationToken cancellationToken) =>
    Results.Ok(await processor.ProcessPendingAsync(500, cancellationToken)));

app.MapPost("/benchmarks/run/{count:int}", async (
    int count,
    SyntheticBenchmarkRunner runner,
    CancellationToken cancellationToken) =>
{
    if (count is < 1 or > 100_000)
    {
        return Results.BadRequest(new { error = "count must be between 1 and 100000" });
    }

    return Results.Ok(await runner.RunAsync(count, cancellationToken));
});

app.MapDelete("/admin/reset", async (SqliteOpsStore store, CancellationToken cancellationToken) =>
{
    await store.ResetAsync(cancellationToken);
    return Results.NoContent();
});

app.Run();

public partial class Program;
