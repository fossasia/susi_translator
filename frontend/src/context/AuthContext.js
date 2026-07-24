import React, { createContext, useState, useContext, useEffect, useCallback } from "react";
import { authAPI } from "@/lib/api";

const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  // Check auth status on mount
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const data = await authAPI.getStatus();
        if (data.authenticated) {
          setIsAuthenticated(true);
          setUser({ email: data.email, name: data.name });
        } else {
          setIsAuthenticated(false);
          setUser(null);
        }
      } catch (error) {
        setIsAuthenticated(false);
        setUser(null);
      } finally {
        setIsLoading(false);
      }
    };
    
    checkAuth();
  }, []);

  const login = useCallback(async (email, password) => {
    const data = await authAPI.login(email, password);
    if (data.status === "success") {
      setIsAuthenticated(true);
      setUser({ email: data.email, name: data.name });
    }
    return data;
  }, []);

  const signup = useCallback(async (name, email, password) => {
    const data = await authAPI.signup(name, email, password);
    if (data.status === "success") {
      setIsAuthenticated(true);
      setUser({ email: data.email, name: data.name });
    }
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authAPI.logout();
    } catch (err) {
      console.error("Logout failed on server, clearing local state anyway");
    } finally {
      setIsAuthenticated(false);
      setUser(null);
    }
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, user, isLoading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
