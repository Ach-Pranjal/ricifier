import { HashRouter, Routes, Route } from "react-router-dom";
import Landing from "./pages/landing/landing.jsx";
import Selection from "./pages/selection/selection.jsx";
import Preview from "./pages/preview/preview.jsx";

function App() {
  return (
    <HashRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/selection" element={<Selection />} />
        <Route path="/preview" element={<Preview />} />
      </Routes>
    </HashRouter>
  );
}

export default App;
