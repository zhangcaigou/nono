import {
  Routes,
  Route
} from "react-router-dom";

import AppLayout from "./components/AppLayout";
import SearchPage from "./pages/SearchPage";
import TaskPage from "./pages/TaskPage";

function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<SearchPage />} />
        <Route path="/tasks/:taskId" element={<TaskPage />} />
      </Routes>
    </AppLayout>
  );
}

export default App;
