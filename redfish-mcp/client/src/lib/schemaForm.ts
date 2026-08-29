export interface JsonSchemaProperty {
  type?: string | string[];
  enum?: unknown[];
  description?: string;
  default?: unknown;
}

export function defaultValueFor(prop: JsonSchemaProperty): unknown {
  if (prop.default !== undefined) return prop.default;
  if (prop.enum && prop.enum.length > 0) return prop.enum[0];
  const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
  switch (type) {
    case "boolean":
      return false;
    case "number":
    case "integer":
      return 0;
    case "object":
      return {};
    case "array":
      return [];
    default:
      return "";
  }
}

export function isSimpleType(prop: JsonSchemaProperty): boolean {
  const type = Array.isArray(prop.type) ? prop.type[0] : prop.type;
  return type === "string" || type === "number" || type === "integer" || type === "boolean";
}

export function buildDefaultArgs(
  properties: Record<string, JsonSchemaProperty> | undefined,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  if (!properties) return {};
  const args: Record<string, unknown> = {};
  for (const [key, prop] of Object.entries(properties)) {
    if (key in overrides) {
      args[key] = overrides[key];
    } else if (isSimpleType(prop) || (prop.enum && prop.enum.length > 0)) {
      args[key] = defaultValueFor(prop);
    }
  }
  return args;
}
