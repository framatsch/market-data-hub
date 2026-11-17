"""Validation helpers shared by fixture and provider request contract tests."""

import json
from pathlib import Path

import httpx
from jsonschema import Draft202012Validator, FormatChecker

FIXTURES = Path(__file__).parent / "fixtures" / "financialdatasets"
OPENAPI = json.loads((FIXTURES / "openapi.json").read_text())


def schema(value):
    """Resolve local OpenAPI refs and translate nullable (including enum nulls)."""
    if isinstance(value, list):
        return [schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        target = OPENAPI
        for part in value["$ref"].removeprefix("#/").split("/"):
            target = target[part]
        value = {**target, **{k: v for k, v in value.items() if k != "$ref"}}
    result = {key: schema(item) for key, item in value.items() if key != "nullable"}
    if value.get("nullable"):
        result = {"anyOf": [result, {"type": "null"}]}
    return result


def validate_response(path: str, status: int, payload):
    response = schema(OPENAPI["paths"][path]["get"]["responses"][str(status)])
    Draft202012Validator(
        response["content"]["application/json"]["schema"],
        format_checker=FormatChecker(),
    ).validate(payload)


def validate_request(request: httpx.Request):
    assert request.method == "GET"
    assert request.url.scheme == "https"
    assert request.url.host == "api.financialdatasets.ai"
    operation = OPENAPI["paths"][request.url.path]["get"]
    security = OPENAPI["components"]["securitySchemes"]["X-API-KEY"]
    assert security["in"] == "header"
    assert request.headers[security["name"]]
    parameters = {item["name"]: item for item in operation.get("parameters", [])}
    assert set(request.url.params) <= set(parameters)
    # A pagination cursor carries the original filters; required query fields
    # may be omitted on subsequent requests per the published description.
    for name, definition in parameters.items():
        if definition.get("required") and "cursor" not in request.url.params:
            assert name in request.url.params, name
        if name not in request.url.params:
            continue
        value = request.url.params[name]
        if definition["schema"].get("type") == "integer":
            value = int(value)
        Draft202012Validator(
            schema(definition["schema"]), format_checker=FormatChecker()
        ).validate(value)
