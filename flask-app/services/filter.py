
    # --- Helper to filter potholes based on query args ---
def filter_potholes(args, data):
    sev_list = args.getlist('severity', type=int)
    start = args.get('start_date')
    end = args.get('end_date')
    conf_min = args.get('conf_min', type=float, default=0.0)

    results = []
    for p in data:
        if sev_list and p['severity'] not in sev_list:
            continue
        if start and p['date'] < start:
            continue
        if end and p['date'] > end:
            continue
        if (p.get('confidence') or 0) < conf_min:
            continue
        results.append(p)
    return results
