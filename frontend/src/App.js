import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Toaster } from "@/components/ui/sonner";
import Home from "@/pages/Home";
import Docs from "@/pages/Docs";
import Pricing from "@/pages/Pricing";
import Playground from "@/pages/Playground";

function App() {
  return (
    <BrowserRouter>
      <Toaster position="top-center" />
      <Routes>
        <Route element={<SiteLayout />}>
          <Route path="/" element={<Home />} />
          <Route path="/docs" element={<Docs />} />
          <Route path="/pricing" element={<Pricing />} />
        </Route>
        <Route path="/demo" element={<Playground />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
