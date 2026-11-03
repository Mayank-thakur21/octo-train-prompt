/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional override of the API base path (defaults to "/api"). */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
