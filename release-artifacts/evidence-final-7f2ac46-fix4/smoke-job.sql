-- Synthetic smoke job for the 7f2ac46-fix4 worker image.
-- A month-end rollup with no source runs: it exercises outbox -> beat ->
-- broker -> worker -> claim -> fenced completion without Last9 or S3.
INSERT INTO jobs (
    id, status, region_code, index_target_id, credential_id,
    start_epoch, end_epoch, chunk_hours, id_batch_size,
    filter_spec, output_format, is_preview,
    rows_written, total_chunks, completed_chunks, rollup_of
) VALUES (
    1001, 'queued', 'ap-southeast-1', 1, 1,
    1700000000, 1702592000, 24, 100,
    $json${
      "aggregation": {
        "regex": "SPAccountId\\s+(?<spid>\\d+)\\s+in\\s+BU\\s+(?<BU>.*?)\\s+API User",
        "group_by": ["BU"],
        "unique_fields": ["spid"]
      },
      "label": "smoke"
    }$json$::json,
    'csv', false,
    0, 0, 0,
    $json2${"schedule_id": 77, "label": "smoke-rollup"}$json2$::json
);

INSERT INTO job_dispatch_outbox (job_id, task_name, status, payload)
VALUES (1001, 'logvault.run_job', 'pending', '{}'::json);
