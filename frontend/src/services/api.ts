import axios from 'axios';

const api = axios.create({
  baseURL: '/',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  // Multi-branch: forward the admin's selected branch (Horizon 3). The backend
  // get_current_branch_id honours this only for admins; others are pinned to
  // their assigned branch. Empty = all/default.
  const branch = sessionStorage.getItem('active_branch');
  if (branch) {
    config.headers['X-Branch-Id'] = branch;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('token');
      sessionStorage.removeItem('user');
      // Dispatch event so React auth hook can react without full page reload
      window.dispatchEvent(new Event('auth:logout'));
    }
    return Promise.reject(error);
  }
);

export default api;
