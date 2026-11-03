import { useEffect } from "react";

export const APP_NAME = "Prompt Engineering Studio";

/** Sets `document.title` to "<page> · Prompt Engineering Studio". */
export function useDocumentTitle(page: string): void {
  useEffect(() => {
    document.title = page ? `${page} · ${APP_NAME}` : APP_NAME;
  }, [page]);
}
