import axios from 'axios';

/**
 * Separate axios instance for Platform Admin API.
 * Uses platform_token from sessionStorage (not the tenant token).
 */
const platformApi = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' },
});

platformApi.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('platform_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

platformApi.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('platform_token');
      sessionStorage.removeItem('platform_user');
      // Trigger re-render so PlatformRoutes shows login page
      window.dispatchEvent(new Event('platform:logout'));
    }
    return Promise.reject(error);
  }
);

export default platformApi;
