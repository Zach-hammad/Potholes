import datetime, random
# --- Dummy Pothole Data Generation (fallback) ---
def generate_dummy_potholes(n=100):
    base_lat, base_lng = 39.9526, -75.1652
    descriptions = [
        "Crack along curb", "Large crater", "Hairline fracture",
        "Pothole near manhole", "Edge collapse", "Multiple small holes",
        "Sunken asphalt", "Long depression", "Water pooling", "Severe washout"
    ]
    today = datetime.date.today()
    data = []
    for i in range(1, n + 1):
        lat = base_lat + random.uniform(-0.03, 0.03)
        lng = base_lng + random.uniform(-0.03, 0.03)
        severity = random.randint(1, 5)
        confidence = round(random.uniform(0.5, 1.0), 2)
        date = (today - datetime.timedelta(days=random.randint(0, 30))).isoformat()
        desc = random.choice(descriptions)
        data.append({
            "id": i,
            "lat": round(lat, 6),
            "lng": round(lng, 6),
            "severity": severity,
            "confidence": confidence,
            "date": date,
            "description": desc
        })
    return data
