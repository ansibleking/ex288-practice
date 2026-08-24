import { useEffect, useState } from "react";
import { listExtraSelectFields } from "../api";
import type { ExtraSelectField } from "../types";

interface Props {
  values: Record<string, string>;
  onChange: (fieldId: string, optionId: string) => void;
  disabled?: boolean;
  onFieldsLoaded?: (fields: ExtraSelectField[]) => void;
}

export function ExtraFieldsSelects({ values, onChange, disabled, onFieldsLoaded }: Props) {
  const [fields, setFields] = useState<ExtraSelectField[]>([]);

  useEffect(() => {
    listExtraSelectFields()
      .then((f) => {
        setFields(f);
        onFieldsLoaded?.(f);
      })
      .catch(() => {
        /* if this can't load, the fields just don't appear -- Jira itself
           will still reject the create with a clear error if one is missing */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (fields.length === 0) return null;

  return (
    <>
      {fields.map((field) => (
        <label key={field.field_id} className="issue-type-select">
          {field.label} (required)
          <select
            value={values[field.field_id] ?? ""}
            onChange={(e) => onChange(field.field_id, e.target.value)}
            disabled={disabled}
          >
            <option value="" disabled>
              Select {field.label.toLowerCase()}…
            </option>
            {field.options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.value}
              </option>
            ))}
          </select>
        </label>
      ))}
    </>
  );
}

export function extraFieldsSatisfied(fields: ExtraSelectField[], values: Record<string, string>): boolean {
  return fields.every((f) => Boolean(values[f.field_id]));
}
