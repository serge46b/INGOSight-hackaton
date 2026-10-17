import { Route, Routes } from "react-router-dom";
import { Shell } from "./Shell";
import { DigestPage } from "./pages/DigestPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ThreadPage } from "./pages/ThreadPage";
import { ThreadsPage } from "./pages/ThreadsPage";

export function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<ThreadsPage />} />
        <Route path="/threads/:id" element={<ThreadPage />} />
        <Route path="/digest" element={<DigestPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  );
}
