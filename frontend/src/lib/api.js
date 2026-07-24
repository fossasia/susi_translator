import axios from "axios";

// Create an Axios instance
// Since we have set "proxy" in package.json to the Flask server, we can use relative paths
const api = axios.create({
  withCredentials: true, // Ensures cookies (like JWT) are sent and received cross-origin
  headers: {
    "Content-Type": "application/json",
  },
});

export const authAPI = {
  login: async (email, password) => {
    const response = await api.post("/auth/api/login", { email, password });
    return response.data;
  },

  signup: async (name, email, password) => {
    const response = await api.post("/auth/api/signup", { name, email, password });
    return response.data;
  },

  logout: async () => {
    const response = await api.post("/auth/api/logout");
    return response.data;
  },

  getStatus: async () => {
    const response = await api.get("/auth/api/status");
    return response.data;
  },
  
  getMe: async () => {
    const response = await api.get("/auth/api/me");
    return response.data;
  }
};

export default api;
