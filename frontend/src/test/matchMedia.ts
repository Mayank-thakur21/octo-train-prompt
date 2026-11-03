/** Controllable `window.matchMedia` stub (jsdom has none) for prefers-color-scheme tests. */

type Listener = (event: MediaQueryListEvent) => void;

let prefersDark = false;
const listeners = new Set<Listener>();

/** Installs the stub with the given initial OS preference. */
export function installMatchMedia(dark: boolean): void {
  prefersDark = dark;
  listeners.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string): MediaQueryList => {
      const isDarkQuery = query.includes("prefers-color-scheme: dark");
      return {
        get matches() {
          return isDarkQuery ? prefersDark : false;
        },
        media: query,
        onchange: null,
        addEventListener: (_type: string, listener: Listener) => listeners.add(listener),
        removeEventListener: (_type: string, listener: Listener) => listeners.delete(listener),
        addListener: (listener: Listener) => listeners.add(listener),
        removeListener: (listener: Listener) => listeners.delete(listener),
        dispatchEvent: () => true,
      } as unknown as MediaQueryList;
    },
  });
}

/** Simulates the OS switching between dark and light. */
export function setSystemDark(dark: boolean): void {
  prefersDark = dark;
  for (const listener of [...listeners]) listener({ matches: dark } as MediaQueryListEvent);
}
