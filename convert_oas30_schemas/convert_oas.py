#
# MIT License
#
# (C) Copyright 2024 Hewlett Packard Enterprise Development LP
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#

import json
from typing import TextIO

import jsonref

class ConversionException(Exception):
    """
    Raised for some errors during the conversion process
    """

def convert_schema(schema):
    if not isinstance(schema, dict):
        raise ConversionException(
            f"Expecting schema to be type dict, but found type {type(schema).__name__}: {schema}")
    if len(schema) == 1:
        key = list(schema.keys())[0]
        if key == '$ref':
            # If this is a $ref, then we're done
            return
        if key == 'not':
            # If this is a not, then we just parse what it maps to
            convert_schema(schema[key])
            return
        if key in { 'oneOf', 'anyOf', 'allOf' }:
            # If this is oneOf, anyOf, or allOf, then it should map to a list, and we need to
            # parse each element of that list
            if not isinstance(schema[key], list):
                raise ConversionException(
                    f"Expecting '{key}' to map to a list, but it does not: {schema}")
            for v in schema[key]:
                convert_schema(v)
            return

    try:
        schema_type = schema["type"]
    except KeyError as exc:
        raise ConversionException(f"Schema is missing 'type' field: {schema}") from exc

    if schema_type == "array":
        _cleanse_array_schema(schema)
    elif schema_type in { "boolean", "string" }:
        _cleanse_generic_schema(schema)
    elif schema_type in { "integer", "number" }:
        _cleanse_numeric_schema(schema)
    elif schema_type == "object":
        _cleanse_object_schema(schema)
    else:
        raise ConversionException(f"Schema has unknown type '{schema_type}': {schema}")


def _cleanse_generic_schema(schema):
    # The nullable keyword works for OAS 3.0 but not 3.1
    if schema.pop("nullable", False):
        schema["type"] = [ schema["type"], "null" ]

    # Remove keywords that are not part of JSON schema, as well as ones which are not needed for
    # validation, and have different meanings between OAS and JSON schema
    for k in ["deprecated", "discriminator", "example", "externalDocs", "readOnly", "writeOnly",
              "xml", "description"]:
        schema.pop(k, None)


def _cleanse_array_schema(schema):
    _cleanse_generic_schema(schema)
    try:
        items_schema = schema["items"]
    except KeyError as exc:
        raise ConversionException(
            f"Array schema is missing required 'items' field: {schema}") from exc
    convert_schema(items_schema)


def _cleanse_numeric_schema(schema):
    _cleanse_generic_schema(schema)
    if any(field in schema for field in [ "exclusiveMinimum", "exclusiveMaximum" ]):
        # Rather than worry about dealing with this programmatically, we should just fail.
        # This is run at build time, so if it fails, the API spec can be fixed before this
        # gets checked in.
        raise ConversionException(
            f"Integer/Number schema has exclusiveMinimum/Maximum field. Schema: {schema}")


def _cleanse_object_schema(schema):
    _cleanse_generic_schema(schema)
    object_properties = schema.get("properties", {})
    if not isinstance(object_properties, dict):
        raise ConversionException(
            f"Object schema has non-dict 'properties' value. Schema: {schema}")
    for v in object_properties.values():
        convert_schema(v)

    # additionalProperties is allowed to map to a schema dict. But it's also allowed to map
    # to a boolean. Or to be absent. If it is present and mapped to a non-empty dict, then we
    # need to cleanse it.
    try:
        additional_properties = schema['additionalProperties']
    except KeyError:
        return
    if not isinstance(additional_properties, dict):
        return
    if not additional_properties:
        return
    convert_schema(additional_properties)


def convert_file(input_file: TextIO, output_file: TextIO|None=None) -> dict:
    """
    Reads in the JSON OpenAPI 3.0.x spec file.
    Converts to OpenAPI 3.1 / JSON schema.
    * Replaces all 'nullable' fields to be compliant with JSON schemas.
    * Replaces all $refs with what they are referencing.
    * Removes keywords which are either invalid or have a different meaning in JSON schemas
      (and that we don't need for our purposes for this file: validating data against
      the schema)
    * Raises an exception in cases where we'd prefer to change the API spec rather than
      handle the conversion here. Since this runs at build time, we'll know quickly
      if a change to the API spec introduces this kind of problem.

    If an output file path is specified, the result is written there in JSON.
    Either way, the result is returned.
    """
    oas = json.load(input_file)

    for oas_schema_name, oas_schema in oas["components"]["schemas"].items():
        try:
            convert_schema(oas_schema)
        except Exception as exc:
            raise ConversionException(f"Error parsing schema {oas_schema_name}") from exc

    # Parse the $refs
    oas_jsonref = jsonref.loads(json.dumps(oas))

    # Replace the $refs
    oas_json_norefs = jsonref.replace_refs(oas_jsonref)

    if output_file:
        # Write to file
        json.dump(oas_json_norefs, output_file)

    return oas_json_norefs
