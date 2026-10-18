import json

from flask import Blueprint, Response, jsonify, render_template, request

from . import models


mindmaps = Blueprint("mindmaps", __name__, url_prefix="/tools/mindmaps")


def body():
    return request.get_json(silent=True) or {}


def api_error(error, status=400):
    return jsonify(error=str(error)), status


@mindmaps.get("")
@mindmaps.get("/")
def index():
    return render_template("mindmaps/index.html")


@mindmaps.get("/new")
def new_map():
    return render_template("mindmaps/editor.html", map_id="new")


@mindmaps.get("/<map_id>")
def editor(map_id):
    if not models.map_row(map_id):
        return render_template("mindmaps/not_found.html"), 404
    return render_template("mindmaps/editor.html", map_id=map_id)


@mindmaps.get("/<map_id>/settings")
def map_settings(map_id):
    if not models.map_row(map_id):
        return render_template("mindmaps/not_found.html"), 404
    return render_template("mindmaps/editor.html", map_id=map_id, open_settings=True)


@mindmaps.get("/api/settings")
def settings_get():
    return jsonify(settings=models.get_settings())


@mindmaps.put("/api/settings")
def settings_put():
    try:
        return jsonify(settings=models.save_settings(body()))
    except ValueError as error:
        return api_error(error)


@mindmaps.get("/api/maps")
def maps_list():
    return jsonify(maps=models.list_maps())


@mindmaps.post("/api/maps")
def maps_create():
    try:
        return jsonify(map=models.create(body())), 201
    except ValueError as error:
        return api_error(error)


@mindmaps.post("/api/maps/import")
def maps_import():
    payload = body()
    document = payload.get("map", payload)
    try:
        return jsonify(map=models.create(document)), 201
    except ValueError as error:
        return api_error(error)


@mindmaps.get("/api/maps/<map_id>")
def maps_get(map_id):
    row = models.map_row(map_id)
    return jsonify(map=models.document(row)) if row else api_error("Mind map not found.", 404)


@mindmaps.put("/api/maps/<map_id>")
def maps_update(map_id):
    try:
        result = models.update(map_id, body())
    except ValueError as error:
        return api_error(error)
    return jsonify(map=result) if result else api_error("Mind map not found.", 404)


@mindmaps.delete("/api/maps/<map_id>")
def maps_delete(map_id):
    return ("", 204) if models.delete(map_id) else api_error("Mind map not found.", 404)


@mindmaps.post("/api/maps/<map_id>/duplicate")
def maps_duplicate(map_id):
    result = models.duplicate(map_id)
    if not result:
        return api_error("Mind map not found.", 404)
    return jsonify(map=result), 201


@mindmaps.get("/api/maps/<map_id>/export")
def maps_export(map_id):
    row = models.map_row(map_id)
    if not row:
        return api_error("Mind map not found.", 404)
    document = json.dumps(models.document(row), indent=2)
    return Response(document, mimetype="application/json", headers={"Content-Disposition": f'attachment; filename="{row["name"]}.mindmap.json"'})
