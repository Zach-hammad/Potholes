import io, csv
import services.filter
from flask import Blueprint, request, jsonify, current_app, send_file, abort

bp = Blueprint('export', __name__, url_prefix = "/api")

@bp.route('/export', methods=['GET'])
def export_data():
    fmt = request.args.get('format', 'csv')
    try:
        data = filter_potholes(request.args, current_app.pothole_data)
    except Exception as e:
        current_app.logger.error(f"Error filtering potholes: {e}")
        abort(400, "Invalid filter parameters")

    if fmt == 'geojson':
        features = []
        for p in data:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [p["lng"], p["lat"]],
                },
                "properties": {
                    k: v for k, v in p.items() if k not in ("lat", "lng")
                }
            })
        return jsonify({
            "type": "FeatureCollection",
            "features": features
        })

    si = io.StringIO()
    fieldnames = list(data[0].keys() )if data else []
    writer = csv.DictWriter(si, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(data)

    output = io.BytesIO(si.getvalues().encode())
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name='potholes.csv'
    )