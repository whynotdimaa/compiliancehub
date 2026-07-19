import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";

import { api, tokenStore } from "./api";
import { Icons } from "./components/ui";
import { Ask } from "./pages/Ask";
import { Documents } from "./pages/Documents";
import { Evaluation } from "./pages/Evaluation";
import { Login } from "./pages/Login";
import { SearchPage } from "./pages/Search";
import type { UserOut } from "./types";

interface AuthState {
  user: UserOut | null;
  ready: boolean;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
}

const AuthContext = createContext<AuthState>(null as unknown as AuthState);
export const useAuth = () => useContext(AuthContext);

function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [ready, setReady] = useState(false);

  const signOut = useCallback(() => {
    tokenStore.clear();
    setUser(null);
  }, []);

  const signIn = useCallback(async (token: string) => {
    tokenStore.set(token);
    setUser(await api.me());
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener("ch-unauthorized", onUnauthorized);
    if (tokenStore.get()) {
      api
        .me()
        .then(setUser)
        .catch(() => tokenStore.clear())
        .finally(() => setReady(true));
    } else {
      setReady(true);
    }
    return () => window.removeEventListener("ch-unauthorized", onUnauthorized);
  }, []);

  return (
    <AuthContext.Provider value={{ user, ready, signIn, signOut }}>{children}</AuthContext.Provider>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="wordmark">ComplianceHub</div>
        <nav className="nav">
          <NavLink to="/documents">{Icons.docs} Documents</NavLink>
          <NavLink to="/ask">{Icons.ask} Ask</NavLink>
          <NavLink to="/search">{Icons.search} Search</NavLink>
          <NavLink to="/evaluation">{Icons.gauge} Evaluation</NavLink>
        </nav>
        <div className="sidebar-footer">
          <div className="whoami">
            <span className="email">{user?.email}</span>
            <span className="role">{user?.role}</span>
          </div>
          <button className="btn btn-ghost" onClick={signOut}>
            {Icons.logout} Sign out
          </button>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

function Protected({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) return null;
  if (!user) return <Navigate to="/login" replace />;
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/documents" element={<Protected><Documents /></Protected>} />
          <Route path="/ask" element={<Protected><Ask /></Protected>} />
          <Route path="/search" element={<Protected><SearchPage /></Protected>} />
          <Route path="/evaluation" element={<Protected><Evaluation /></Protected>} />
          <Route path="*" element={<Navigate to="/documents" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
