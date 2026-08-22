param(
    [string]$BaseUrl = "http://127.0.0.1:5087"
)

$ErrorActionPreference = "Stop"

foreach ($count in 100, 1000, 10000) {
    Invoke-RestMethod -Method Post -Uri "$BaseUrl/benchmarks/run/$count"
}
