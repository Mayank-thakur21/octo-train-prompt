import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { QueryProvider } from "./context/QueryProvider";
import { SettingsProvider } from "./context/SettingsProvider";
import { ToastProvider } from "./context/ToastProvider";
import "./index.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root is missing from index.html.");

createRoot(container).render(
  <StrictMode>
    <ErrorBoundary scope="root">
      <BrowserRouter>
        <SettingsProvider>
          <ToastProvider>
            <QueryProvider>
              <App />
            </QueryProvider>
          </ToastProvider>
        </SettingsProvider>
      </BrowserRouter>
    </ErrorBoundary>
  </StrictMode>,
);
