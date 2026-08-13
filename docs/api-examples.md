# API Examples

Start the API:

```bash
uvicorn support_operations_intelligence_platform.api.app:create_app --factory --reload
```

## Health

```bash
curl -i http://127.0.0.1:8000/health
```

Expected response:

```http
HTTP/1.1 200 OK
content-type: application/json

{"status":"ok"}
```

## Seed Demo Data

```bash
curl -i -X POST http://127.0.0.1:8000/demo/seed
```

Expected response:

```http
HTTP/1.1 200 OK
content-type: application/json

{"message":"demo data seeded"}
```

## Submit Synthetic Event

```bash
curl -i -X POST http://127.0.0.1:8000/events \
  -H "content-type: application/json" \
  -d '{"asset_external_id":"PUMP-101","source":"north-gateway","category":"offline","severity":88,"message":"Heartbeat missing for the synthetic pump controller"}'
```

Expected shape:

```http
HTTP/1.1 200 OK
content-type: application/json

{
  "event_id": 1,
  "incident_id": 1,
  "action_id": 1,
  "rule_name": "Offline asset escalation"
}
```

