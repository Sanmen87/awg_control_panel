"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

type AuthContextValue = {
  token: string | null;
  setToken: (token: string | null) => void;
  logout: () => void;
  ready: boolean;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: Readonly<{ children: React.ReactNode }>) {
  const [token, setTokenState] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = window.localStorage.getItem("awg-token");
    if (stored) {
      setTokenState(stored);
    }
    setReady(true);

    const handleAuthExpired = () => {
      setTokenState(null);
      window.localStorage.removeItem("awg-token");
    };

    window.addEventListener("awg-auth-expired", handleAuthExpired);
    return () => {
      window.removeEventListener("awg-auth-expired", handleAuthExpired);
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      token,
      ready,
      setToken: (nextToken) => {
        setTokenState(nextToken);
        if (nextToken) {
          window.localStorage.setItem("awg-token", nextToken);
        } else {
          window.localStorage.removeItem("awg-token");
        }
      },
      logout: () => {
        setTokenState(null);
        window.localStorage.removeItem("awg-token");
      }
    }),
    [token, ready]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
