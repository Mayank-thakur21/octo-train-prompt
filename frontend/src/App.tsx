import { lazy } from "react";
import { Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";

// Pages are split into their own chunks and loaded on first visit.
const PlaygroundPage = lazy(() => import("./pages/PlaygroundPage"));
const ComparePage = lazy(() => import("./pages/ComparePage"));
const LibraryPage = lazy(() => import("./pages/LibraryPage"));
const PromptDetailPage = lazy(() => import("./pages/PromptDetailPage"));
const SuitesPage = lazy(() => import("./pages/SuitesPage"));
const SuiteDetailPage = lazy(() => import("./pages/SuiteDetailPage"));
const EvalsPage = lazy(() => import("./pages/EvalsPage"));
const EvalDetailPage = lazy(() => import("./pages/EvalDetailPage"));
const HistoryPage = lazy(() => import("./pages/HistoryPage"));
const HistoryDetailPage = lazy(() => import("./pages/HistoryDetailPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

/** Route table (contract section 8.4). */
export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/playground" replace />} />
        <Route path="playground" element={<PlaygroundPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="library" element={<LibraryPage />} />
        <Route path="library/:promptId" element={<PromptDetailPage />} />
        <Route path="suites" element={<SuitesPage />} />
        <Route path="suites/:suiteId" element={<SuiteDetailPage />} />
        <Route path="evals" element={<EvalsPage />} />
        <Route path="evals/:evalId" element={<EvalDetailPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="history/:historyId" element={<HistoryDetailPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
