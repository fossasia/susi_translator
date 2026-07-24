import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { SiteLayout } from "@/components/site/SiteLayout";
import { Toaster } from "@/components/ui/sonner";
import Home from "@/pages/Home";
import Docs from "@/pages/Docs";
import Pricing from "@/pages/Pricing";
import Playground from "@/pages/Playground";
import Login from "@/pages/Login";
import Signup from "@/pages/Signup";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-center" />
        <Routes>
          <Route element={<SiteLayout />}>
            <Route path="/" element={<Home />} />
            <Route path="/docs" element={<Docs />} />
            <Route path="/pricing" element={<Pricing />} />
          </Route>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route
            path="/demo"
            element={
              <ProtectedRoute>
                <Playground />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
