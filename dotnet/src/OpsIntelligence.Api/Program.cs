using Microsoft.Extensions.Options;
using OpsIntelligence.Api.Domain;

var builder = WebApplication.CreateBuilder(args);

builder.Services.Configure<OpsOptions>(builder.Configuration.GetSection("OpsIntelligence"));
builder.Services.PostConfigure<OpsOptions>(options => options.ApplyEnvironment());
builder.Services.AddSingleton<OpsDatabase>();
builder.Services.AddSingleton<OpsEngine>();
builder.Services.AddSingleton<ActionProcessor>();

var backgroundEnabled = Environment.GetEnvironmentVariable("OPS_ENABLE_BACKGROUND");
if (backgroundEnabled is "1" or "true" or "TRUE" or "yes" or "YES")
{
    builder.Services.AddHostedService<QueuedActionBackgroundService>();
}

var app = builder.Build();
app.Services.GetRequiredService<OpsDatabase>();

app.MapGet("/health", () => Results.Ok(new { status = "ok", stack = ".NET 10 / ASP.NET Core" }));

app.MapPost(
    "/events",
    (EventRequest request, OpsEngine engine) =>
    {
        if (string.IsNullOrWhiteSpace(request.AssetId)
            || string.IsNullOrWhiteSpace(request.Source)
            || string.IsNullOrWhiteSpace(request.Category)
            || string.IsNullOrWhiteSpace(request.Message)
            || request.Severity is < 1 or > 100)
        {
            return Results.BadRequest(new { error = "invalid event payload" });
        }

        return Results.Ok(engine.Process(request));
    });

app.MapGet("/metrics", (OpsDatabase database) => Results.Ok(database.GetMetrics()));
app.MapGet("/incidents", (OpsDatabase database) => Results.Ok(database.ListIncidents()));
app.MapGet("/actions", (OpsDatabase database) => Results.Ok(database.ListActions()));
app.MapGet("/audit", (OpsDatabase database) => Results.Ok(database.ListAudit()));
app.MapPost("/maintenance/process-actions", (ActionProcessor processor) => Results.Ok(processor.ProcessQueuedActions()));
app.MapDelete("/admin/reset", (OpsDatabase database) => Results.Ok(new ResetResult(database.Reset())));

app.Run();

public partial class Program;
