import yaml, sys
sys.stdout.reconfigure(encoding='utf-8')
report = r'C:\Users\Onyema Ifechukwu\Downloads\admin_postman_hybrid_report_20260513-184514.yaml'
with open(report, encoding='utf-8') as f:
    data = yaml.safe_load(f)
results = data.get('results', [])
by_api = {}
for r in results:
    api = r.get('api_id', 'UNKNOWN')
    by_api.setdefault(api, []).append(r)
for api, tcs in sorted(by_api.items()):
    passes = sum(1 for t in tcs if t.get('status') == 'PASS')
    fails  = sum(1 for t in tcs if t.get('status') == 'FAIL')
    blks   = sum(1 for t in tcs if t.get('status') == 'BLOCKED')
    print(f'=== {api} ({len(tcs)} TCs: {passes}P/{fails}F/{blks}B) ===')
    for t in sorted(tcs, key=lambda x: x.get('tc_id', '')):
        status = t.get('status')
        if status not in ('FAIL', 'BLOCKED'):
            continue
        tc_id    = t.get('tc_id', '')
        scenario = t.get('scenario', '')
        code     = t.get('actual_status_code', '')
        tag      = t.get('failure_tag', '')
        reason   = str(t.get('failure_reason', ''))[:180]
        print(f'  [{status}] {tc_id} | {scenario}')
        print(f'           code={code} | tag={tag}')
        if reason and reason != 'None':
            print(f'           {reason}')
    print()
