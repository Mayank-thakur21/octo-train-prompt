import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router";

export type FilterValues = Record<string, string | string[]>;

/**
 * List filters, search text and page offset kept in the query string, so Back
 * (or a reload, or a shared link) restores the same view.
 *
 * `defaults` must be a module-level constant. A value equal to its default is
 * left out of the URL; array values map to repeated parameters
 * (`?tag=a&tag=b`). `update` changes several values in one navigation, which
 * replaces the current history entry instead of adding one per keystroke.
 */
export function useUrlFilters<T extends FilterValues>(defaults: T): [T, (changes: Partial<T>) => void] {
  const [params, setParams] = useSearchParams();

  const values = useMemo(() => {
    const result: FilterValues = { ...defaults };
    for (const [name, fallback] of Object.entries(defaults)) {
      if (Array.isArray(fallback)) {
        const all = params.getAll(name);
        if (all.length > 0) result[name] = all;
      } else {
        const value = params.get(name);
        if (value !== null) result[name] = value;
      }
    }
    return result as T;
  }, [params, defaults]);

  const update = useCallback(
    (changes: Partial<T>) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [name, value] of Object.entries(changes) as Array<[string, string | string[] | undefined]>) {
            if (value === undefined) continue;
            next.delete(name);
            const fallback = defaults[name];
            if (Array.isArray(value)) {
              for (const item of value) next.append(name, item);
            } else if (value !== fallback) {
              next.set(name, value);
            }
          }
          return next;
        },
        { replace: true },
      );
    },
    [setParams, defaults],
  );

  return [values, update];
}

/** A page offset read from the URL: a whole number >= 0, else 0. */
export function parseOffset(raw: string): number {
  const value = Number.parseInt(raw, 10);
  return Number.isInteger(value) && value > 0 ? value : 0;
}
